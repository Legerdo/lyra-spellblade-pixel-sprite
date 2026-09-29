extends Node
## Lyra spellblade driver, loaded by the stable Pixelorama v1.2.3 desktop build as an extension.
## Does nothing unless LYRA_MODE is set, so a normal Pixelorama session is unaffected.
##   create  : build the project from rendered layer cels, save a native .pxo
##   inspect : reopen a .pxo through Pixelorama and dump every cel + metadata for verification
##   gui     : open the .pxo in the real editor window, 100% view / zoom / onion-skin captures,
##             timeline playback observation


func _ready() -> void:
	var mode := OS.get_environment("LYRA_MODE")
	if mode.is_empty() or mode == "probe":
		if mode == "probe":
			print("LYRA probe ", Global.current_version)
			get_tree().quit.call_deferred(0)
		return
	_run.call_deferred(mode)


func _run(mode: String) -> void:
	await get_tree().process_frame
	await get_tree().process_frame
	var report := {"mode": mode, "pixelorama": Global.current_version,
		"engine": Engine.get_version_info().string, "ok": false}
	var code := 1
	if mode == "create":
		code = _create(report)
	elif mode == "inspect":
		code = _inspect(report)
	elif mode == "gui":
		code = await _gui(report)
	var out := OS.get_environment("LYRA_REPORT")
	var f := FileAccess.open(out, FileAccess.WRITE)
	f.store_string(JSON.stringify(report, "\t"))
	f.close()
	print("LYRA_DONE ", mode, " code=", code)
	get_tree().quit(code)


func _read_json(path: String) -> Variant:
	return JSON.parse_string(FileAccess.get_file_as_string(path))


func _create(report: Dictionary) -> int:
	var m: Dictionary = _read_json(OS.get_environment("LYRA_MANIFEST"))
	var size := Vector2i(int(m.width), int(m.height))
	var project := Project.new([], str(m.name), size)
	for layer_name: String in m.layers:
		var layer := PixelLayer.new(project, layer_name)
		layer.index = project.layers.size()
		project.layers.append(layer)
	var order: Array[int] = []
	for i in project.layers.size():
		order.append(i)
	project.ordered_layers = order
	project.fps = float(m.fps)
	project.user_data = JSON.stringify(m.user_data)
	var base := OS.get_environment("LYRA_SRC")
	var loaded := 0
	for fd: Dictionary in m.frames:
		var cels: Array[BaseCel] = []
		for rel: String in fd.cels:
			var img := Image.load_from_file(base.path_join(rel))
			img.convert(Image.FORMAT_RGBA8)
			if img.get_size() != size:
				report["error"] = "cel size mismatch " + rel
				return 1
			var ext := ImageExtended.new()
			ext.copy_from_custom(img)
			cels.append(PixelCel.new(ext))
			loaded += 1
		var frame := Frame.new(cels, float(fd.duration_ms) / 1000.0 * project.fps)
		frame.user_data = str(fd.get("id", ""))
		project.frames.append(frame)
	for td: Dictionary in m.tags:
		project.animation_tags.append(
			AnimationTag.new(str(td.name), Color(str(td.color)), int(td.from), int(td.to)))
	# project palette (the locked authoring palette)
	var colors := PackedColorArray()
	for hex: String in m.palette:
		colors.append(Color(hex))
	var pal: Palette = Palettes.fill_imported_palette_with_colors(str(m.palette_name), colors)
	pal.is_project_palette = true
	project.palettes[pal.name] = pal
	project.project_current_palette_name = pal.name
	# export profile: 5-column grid in timeline order, native scale, nearest
	project.export_profile.orientation = Export.Orientation.ROWS
	project.export_profile.lines_count = int(m.sheet_columns)
	project.export_profile.crop_mode = Export.CropMode.NONE
	project.export_profile.resize = 100
	project.export_profile.interpolation = Image.INTERPOLATE_NEAREST
	project.export_profile.file_name = str(m.name)
	Global.projects.append(project)
	var pxo := OS.get_environment("LYRA_PXO")
	OpenSave.set_new_imported_tab(project, pxo)
	project.export_profile.directory_path = ""  # don't persist a machine-specific path
	var saved := OpenSave.save_pxo_file(pxo, false, true, project)
	report["saved"] = saved
	report["cels_loaded"] = loaded
	report["frames"] = project.frames.size()
	report["layers"] = project.layers.size()
	report["ok"] = saved
	return 0 if saved else 1


func _inspect(report: Dictionary) -> int:
	var pxo := OS.get_environment("LYRA_PXO")
	OpenSave.open_pxo_file(pxo)
	var project := Global.current_project
	var dump := OS.get_environment("LYRA_DUMP")
	DirAccess.make_dir_recursive_absolute(dump)
	report["name"] = project.name
	report["size"] = [project.size.x, project.size.y]
	report["fps"] = project.fps
	report["frames"] = project.frames.size()
	var layers := []
	for l in project.layers:
		layers.append({"name": l.name, "type": l.get_layer_type(), "visible": l.visible})
	report["layers"] = layers
	var tags := []
	for t in project.animation_tags:
		tags.append({"name": t.name, "from": t.from, "to": t.to})
	report["tags"] = tags
	var durations := []
	for i in project.frames.size():
		var frame := project.frames[i]
		durations.append(roundi(frame.duration / project.fps * 1000.0))
		for j in frame.cels.size():
			var img: Image = frame.cels[j].get_image()
			img.save_png(dump.path_join("f%02d_l%d.png" % [i, j]))
	report["durations_ms"] = durations
	var pals := {}
	for pname in project.palettes:
		var p: Palette = project.palettes[pname]
		var cols := []
		for c in p.colors.values():
			cols.append(c.color.to_html(false))
		pals[pname] = cols
	report["project_palettes"] = pals
	report["current_palette"] = project.project_current_palette_name
	report["export_orientation"] = project.export_profile.orientation
	report["export_lines"] = project.export_profile.lines_count
	report["ok"] = true
	return 0


func _shot(path: String) -> void:
	await RenderingServer.frame_post_draw
	get_viewport().get_texture().get_image().save_png(path)


func _gui(report: Dictionary) -> int:
	var shots := OS.get_environment("LYRA_SHOTS")
	DirAccess.make_dir_recursive_absolute(shots)
	OpenSave.open_pxo_file(OS.get_environment("LYRA_PXO"))
	var project := Global.current_project
	await get_tree().create_timer(0.8).timeout
	if is_instance_valid(Global.control.splash_dialog):
		Global.control.splash_dialog.hide()
	get_window().title = "Lyra Spellblade QA - Pixelorama " + Global.current_version
	await get_tree().create_timer(0.3).timeout
	var cam: CanvasCamera = Global.camera
	# 1) native 100% view, every tag's first/key frames
	cam.zoom_100()
	var natives := []
	for i in [0, 1, 2, 5, 11, 17]:
		project.change_cel(i)
		await get_tree().create_timer(0.12).timeout
		cam.zoom_100()
		await get_tree().process_frame
		report["zoom_at_native"] = cam.zoom.x
		var p := shots.path_join("native100_f%02d.png" % i)
		await _shot(p)
		natives.append(p.get_file())
	report["native_100_shots"] = natives
	# 2) zoomed pixel inspection with pixel grid
	Global.draw_pixel_grid = true
	Global.pixel_grid_show_at_zoom = 400.0
	cam.fit_to_frame(project.size)
	await get_tree().create_timer(0.2).timeout
	report["zoom_fit"] = cam.zoom.x
	for i in [0, 14]:
		project.change_cel(i)
		await get_tree().create_timer(0.12).timeout
		await _shot(shots.path_join("zoom_grid_f%02d.png" % i))
	Global.draw_pixel_grid = false
	# 3) onion skin (previous + next) on run and attack frames
	Global.onion_skinning_past_rate = 1
	Global.onion_skinning_future_rate = 1
	Global.onion_skinning_blue_red = true
	if not Global.onion_skinning:
		Global.animation_timeline._on_OnionSkinning_pressed()
	for i in [4, 10, 16]:
		project.change_cel(i)
		Global.canvas.refresh_onion()
		await get_tree().create_timer(0.15).timeout
		await _shot(shots.path_join("onion_f%02d.png" % i))
	report["onion_skinning"] = Global.onion_skinning
	Global.animation_timeline._on_OnionSkinning_pressed()
	# 4) playback: the real timeline Play button across the run tag
	project.change_cel(2)
	Global.animation_timeline.play_forward.button_pressed = true
	var seen: Array[int] = []
	var t0 := Time.get_ticks_msec()
	while Time.get_ticks_msec() - t0 < 1400:
		await get_tree().process_frame
		if seen.is_empty() or seen[-1] != project.current_frame:
			seen.append(project.current_frame)
	Global.animation_timeline.play_forward.button_pressed = false
	report["playback_frames_seen"] = seen
	report["ok"] = seen.size() > 3
	return 0 if report["ok"] else 1
