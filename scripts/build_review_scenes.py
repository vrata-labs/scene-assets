import argparse
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import bpy
from mathutils import Vector


BLENDER_VERSION = (4, 5, 12)
SKIP_RENDER = False
RELEASE_VERSION = ""
TEXTURE_SIZE = 256
PUNCTUAL_LIGHT_ENERGY_SCALE = 0.0005


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--skip-render", action="store_true")
    return parser.parse_args(argv)


def color(hex_value):
    value = hex_value.removeprefix("#")
    return tuple(int(value[index : index + 2], 16) / 255 for index in (0, 2, 4)) + (1.0,)


def reset_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in (
        bpy.data.meshes,
        bpy.data.curves,
        bpy.data.materials,
        bpy.data.cameras,
        bpy.data.lights,
        bpy.data.images,
        bpy.data.worlds,
    ):
        for block in list(collection):
            collection.remove(block)


def clamp(value, minimum=0.0, maximum=1.0):
    return max(minimum, min(maximum, value))


def pattern_height(pattern, u, v):
    if pattern == "wood":
        grain = math.sin((v * 10.0 + math.sin(u * 5.0) * 0.7) * math.tau)
        fine = math.sin((v * 34.0 + u * 2.0) * math.tau) * 0.28
        return 0.5 + grain * 0.34 + fine * 0.16
    if pattern == "textile":
        warp = math.sin(u * 22.0 * math.tau)
        weft = math.sin(v * 22.0 * math.tau)
        return 0.5 + warp * 0.11 + weft * 0.11 + warp * weft * 0.045
    if pattern == "carpet":
        noise = math.sin((u * 71.0 + v * 43.0) * math.tau) * math.sin((u * 37.0 - v * 59.0) * math.tau)
        return 0.5 + noise * 0.24
    if pattern == "stone":
        vein = math.sin((u * 4.5 + v * 2.1 + math.sin(v * 8.0) * 0.12) * math.tau)
        grain = math.sin((u * 29.0 - v * 17.0) * math.tau) * 0.12
        return 0.5 + vein * 0.25 + grain
    if pattern == "plaster":
        broad = math.sin((u * 9.0 + v * 13.0) * math.tau)
        fine = math.sin((u * 31.0 - v * 23.0) * math.tau)
        return 0.5 + broad * 0.11 + fine * 0.06
    return 0.5


def make_pattern_images(name, base_color, pattern):
    base_rgba = color(base_color)
    color_image = bpy.data.images.new(f"{name} Base Color", width=TEXTURE_SIZE, height=TEXTURE_SIZE, alpha=False)
    color_image.colorspace_settings.name = "sRGB"
    normal_image = bpy.data.images.new(f"{name} Normal", width=TEXTURE_SIZE, height=TEXTURE_SIZE, alpha=False)
    normal_image.colorspace_settings.name = "Non-Color"
    color_pixels = []
    normal_pixels = []
    epsilon = 1.0 / TEXTURE_SIZE
    normal_strength = {
        "wood": 2.0,
        "textile": 0.42,
        "carpet": 0.7,
        "stone": 0.75,
        "plaster": 0.3,
    }.get(pattern, 1.0)
    shade_settings = {
        "wood": (0.83, 0.3),
        "textile": (0.96, 0.08),
        "carpet": (0.94, 0.12),
        "stone": (0.9, 0.2),
        "plaster": (0.97, 0.06),
    }

    for y in range(TEXTURE_SIZE):
        v = (y + 0.5) / TEXTURE_SIZE
        for x in range(TEXTURE_SIZE):
            u = (x + 0.5) / TEXTURE_SIZE
            height = pattern_height(pattern, u, v)
            shade_base, shade_range = shade_settings.get(pattern, (0.9, 0.2))
            shade = shade_base + height * shade_range
            color_pixels.extend((
                clamp(base_rgba[0] * shade),
                clamp(base_rgba[1] * shade),
                clamp(base_rgba[2] * shade),
                1.0,
            ))
            dx = pattern_height(pattern, u + epsilon, v) - pattern_height(pattern, u - epsilon, v)
            dy = pattern_height(pattern, u, v + epsilon) - pattern_height(pattern, u, v - epsilon)
            nx = -dx * normal_strength
            ny = -dy * normal_strength
            nz = 1.0
            length = math.sqrt(nx * nx + ny * ny + nz * nz)
            normal_pixels.extend((nx / length * 0.5 + 0.5, ny / length * 0.5 + 0.5, nz / length * 0.5 + 0.5, 1.0))

    color_image.pixels.foreach_set(color_pixels)
    normal_image.pixels.foreach_set(normal_pixels)
    color_image.pack()
    normal_image.pack()
    return color_image, normal_image


def make_material(
    name,
    base_color,
    roughness=0.65,
    metallic=0.0,
    emission=None,
    emission_strength=0.0,
    pattern=None,
    coat_weight=0.0,
    coat_roughness=0.2,
    sheen_weight=0.0,
):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    material.diffuse_color = color(base_color)
    principled = material.node_tree.nodes.get("Principled BSDF")
    principled.inputs["Base Color"].default_value = color(base_color)
    principled.inputs["Roughness"].default_value = roughness
    principled.inputs["Metallic"].default_value = metallic
    if emission:
        emission_input = principled.inputs.get("Emission Color") or principled.inputs.get("Emission")
        if emission_input:
            emission_input.default_value = color(emission)
        strength_input = principled.inputs.get("Emission Strength")
        if strength_input:
            strength_input.default_value = emission_strength
    coat_input = principled.inputs.get("Coat Weight")
    if coat_input:
        coat_input.default_value = coat_weight
    coat_roughness_input = principled.inputs.get("Coat Roughness")
    if coat_roughness_input:
        coat_roughness_input.default_value = coat_roughness
    sheen_input = principled.inputs.get("Sheen Weight")
    if sheen_input:
        sheen_input.default_value = sheen_weight
    if pattern:
        color_image, normal_image = make_pattern_images(name, base_color, pattern)
        color_node = material.node_tree.nodes.new("ShaderNodeTexImage")
        color_node.name = f"{name} Base Color"
        color_node.image = color_image
        material.node_tree.links.new(color_node.outputs["Color"], principled.inputs["Base Color"])
        normal_texture_node = material.node_tree.nodes.new("ShaderNodeTexImage")
        normal_texture_node.name = f"{name} Normal"
        normal_texture_node.image = normal_image
        normal_map_node = material.node_tree.nodes.new("ShaderNodeNormalMap")
        normal_map_node.inputs["Strength"].default_value = 0.38
        material.node_tree.links.new(normal_texture_node.outputs["Color"], normal_map_node.inputs["Color"])
        material.node_tree.links.new(normal_map_node.outputs["Normal"], principled.inputs["Normal"])
    return material


def assign_material(obj, material):
    obj.data.materials.append(material)


def apply_bevel(obj, width=0.06, segments=3):
    if width <= 0:
        return
    modifier = obj.modifiers.new(name="Edge Softening", type="BEVEL")
    modifier.width = width
    modifier.segments = segments
    modifier.limit_method = "ANGLE"
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=modifier.name)


def add_box(name, location, dimensions, material, bevel=0.05, rotation=0.0):
    bpy.ops.mesh.primitive_cube_add(location=location, rotation=(0.0, 0.0, rotation))
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    apply_bevel(obj, min(bevel, min(dimensions) * 0.25))
    assign_material(obj, material)
    return obj


def join_mesh_objects(name, objects):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.join()
    joined = bpy.context.object
    joined.name = name
    joined.data.name = name

    materials = []
    material_indices = {}
    slot_remap = {}
    for slot_index, slot in enumerate(joined.material_slots):
        material_key = slot.material.as_pointer()
        if material_key not in material_indices:
            material_indices[material_key] = len(materials)
            materials.append(slot.material)
        slot_remap[slot_index] = material_indices[material_key]
    polygon_material_indices = [slot_remap[polygon.material_index] for polygon in joined.data.polygons]
    joined.data.materials.clear()
    for material in materials:
        joined.data.materials.append(material)
    for polygon, material_index in zip(joined.data.polygons, polygon_material_indices):
        polygon.material_index = material_index
    return joined


def add_cylinder(name, location, radius, depth, material, scale_xy=(1.0, 1.0), vertices=48, bevel=0.04):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale.x = scale_xy[0]
    obj.scale.y = scale_xy[1]
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    apply_bevel(obj, min(bevel, depth * 0.2))
    triangulate = obj.modifiers.new(name="Tangent Triangulation", type="TRIANGULATE")
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=triangulate.name)
    assign_material(obj, material)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    return obj


def add_sphere(name, location, scale, material):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    assign_material(obj, material)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    return obj


def add_torus(name, location, major_radius, minor_radius, material, rotation=(0.0, 0.0, 0.0)):
    bpy.ops.mesh.primitive_torus_add(
        major_segments=64,
        minor_segments=12,
        major_radius=major_radius,
        minor_radius=minor_radius,
        location=location,
        rotation=rotation,
    )
    obj = bpy.context.object
    obj.name = name
    assign_material(obj, material)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    return obj


def add_area_light(name, location, target, energy, light_color, size=4.0):
    data = bpy.data.lights.new(name=name, type="AREA")
    data.energy = energy
    data.color = color(light_color)[:3]
    data.shape = "DISK"
    data.size = size
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    point_at(obj, target)
    return obj


def point_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def add_point_light(name, location, energy, light_color, radius=0.35, cutoff=8.0):
    data = bpy.data.lights.new(name=name, type="POINT")
    # Blender exports point/spot watts as candela; keep runtime lights below clipping range.
    data.energy = energy * PUNCTUAL_LIGHT_ENERGY_SCALE
    data.color = color(light_color)[:3]
    data.shadow_soft_size = radius
    data.use_custom_distance = True
    data.cutoff_distance = cutoff
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    return obj


def add_spot_light(name, location, target, energy, light_color, size=math.radians(55), blend=0.55, cutoff=12.0):
    data = bpy.data.lights.new(name=name, type="SPOT")
    data.energy = energy * PUNCTUAL_LIGHT_ENERGY_SCALE
    data.color = color(light_color)[:3]
    data.spot_size = size
    data.spot_blend = blend
    data.shadow_soft_size = 0.3
    data.use_custom_distance = True
    data.cutoff_distance = cutoff
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    point_at(obj, target)
    return obj


def add_room_shell(prefix, width, depth, height, floor_material, wall_material, trim_material):
    add_box(f"{prefix}_Floor", (0.0, 0.0, -0.1), (width, depth, 0.2), floor_material, bevel=0.02)
    add_box(f"{prefix}_BackWall", (0.0, depth / 2 - 0.1, height / 2), (width, 0.2, height), wall_material, bevel=0.02)
    add_box(f"{prefix}_LeftWall", (-width / 2 + 0.1, 0.0, height / 2), (0.2, depth, height), wall_material, bevel=0.02)
    add_box(f"{prefix}_RightWall", (width / 2 - 0.1, 0.0, height / 2), (0.2, depth, height), wall_material, bevel=0.02)
    add_box(f"{prefix}_Ceiling", (0.0, 0.0, height - 0.06), (width, depth, 0.12), wall_material, bevel=0.02)
    add_box(f"{prefix}_BackBaseboard", (0.0, depth / 2 - 0.22, 0.15), (width - 0.3, 0.12, 0.3), trim_material, bevel=0.03)
    add_box(f"{prefix}_LeftBaseboard", (-width / 2 + 0.22, 0.0, 0.15), (0.12, depth - 0.3, 0.3), trim_material, bevel=0.03)
    add_box(f"{prefix}_RightBaseboard", (width / 2 - 0.22, 0.0, 0.15), (0.12, depth - 0.3, 0.3), trim_material, bevel=0.03)


def add_chair(prefix, center, facing, materials, width=0.72, depth=0.7, seat_height=0.5, arms=True):
    forward = Vector((facing[0], facing[1]))
    forward.normalize()
    right = Vector((forward.y, -forward.x))
    rotation = math.atan2(-forward.x, forward.y)
    x, y = center
    parts = []
    parts.append(add_box(
        f"{prefix}_Seat",
        (x, y, seat_height),
        (width, depth, 0.16),
        materials[0],
        bevel=0.08,
        rotation=rotation,
    ))
    parts.append(add_box(
        f"{prefix}_SeatCushion",
        (x, y, seat_height + 0.11),
        (width * 0.88, depth * 0.84, 0.12),
        materials[0],
        bevel=0.055,
        rotation=rotation,
    ))
    back_center = Vector((x, y)) - forward * (depth * 0.42)
    parts.append(add_box(
        f"{prefix}_Back",
        (back_center.x, back_center.y, seat_height + 0.55),
        (width, 0.16, 0.92),
        materials[0],
        bevel=0.08,
        rotation=rotation,
    ))
    cushion_center = back_center + forward * 0.025
    parts.append(add_box(
        f"{prefix}_BackCushion",
        (cushion_center.x, cushion_center.y, seat_height + 0.56),
        (width * 0.86, 0.11, 0.68),
        materials[0],
        bevel=0.055,
        rotation=rotation,
    ))
    for side in (-1.0, 1.0):
        for longitudinal in (-1.0, 1.0):
            leg_xy = Vector((x, y)) + right * (side * width * 0.34) + forward * (longitudinal * depth * 0.28)
            parts.append(add_cylinder(
                f"{prefix}_Leg_{side}_{longitudinal}",
                (leg_xy.x, leg_xy.y, seat_height * 0.5),
                0.035,
                seat_height,
                materials[1],
                vertices=16,
                bevel=0.01,
            ))
    if arms:
        for side in (-1.0, 1.0):
            arm_xy = Vector((x, y)) + right * (side * width * 0.56)
            parts.append(add_box(
                f"{prefix}_Arm_{side}",
                (arm_xy.x, arm_xy.y, seat_height + 0.34),
                (0.09, depth * 0.72, 0.1),
                materials[1],
                bevel=0.025,
                rotation=rotation,
            ))
            for longitudinal in (-1.0, 1.0):
                post_xy = arm_xy + forward * (longitudinal * depth * 0.28)
                parts.append(add_cylinder(
                    f"{prefix}_ArmPost_{side}_{longitudinal}",
                    (post_xy.x, post_xy.y, seat_height + 0.18),
                    0.028,
                    0.34,
                    materials[1],
                    vertices=12,
                    bevel=0.008,
                ))
    return join_mesh_objects(prefix, parts)


def add_planter(prefix, location, pot_material, leaf_material, scale=1.0):
    x, y, z = location
    add_cylinder(f"{prefix}_Pot", (x, y, z + 0.28 * scale), 0.3 * scale, 0.56 * scale, pot_material, vertices=32)
    for index, offset in enumerate(((-0.18, 0.0), (0.15, 0.06), (0.0, -0.14), (0.05, 0.18))):
        add_sphere(
            f"{prefix}_Leaf_{index}",
            (x + offset[0] * scale, y + offset[1] * scale, z + (0.72 + index * 0.1) * scale),
            (0.22 * scale, 0.12 * scale, 0.48 * scale),
            leaf_material,
        )


def add_back_screen(prefix, center, size, frame_material, screen_material, accent_material):
    x, y, z = center
    width, height = size
    add_box(f"{prefix}_Frame", (x, y, z), (width + 0.35, 0.18, height + 0.35), frame_material, bevel=0.1)
    add_box(f"{prefix}_Screen", (x, y - 0.12, z), (width, 0.05, height), screen_material, bevel=0.04)
    bar_width = width * 0.09
    base_x = x - width * 0.28
    overlays = []
    for index, ratio in enumerate((0.35, 0.62, 0.48, 0.78)):
        bar_height = height * ratio * 0.55
        overlays.append(add_box(
            f"{prefix}_Chart_{index}",
            (base_x + index * bar_width * 1.75, y - 0.155, z - height * 0.22 + bar_height / 2),
            (bar_width, 0.018, bar_height),
            accent_material,
            bevel=0.02,
        ))
    overlays.append(add_box(
        f"{prefix}_ChartLine",
        (x + width * 0.22, y - 0.16, z + height * 0.25),
        (width * 0.3, 0.02, 0.05),
        accent_material,
        bevel=0.02,
    ))
    join_mesh_objects(f"{prefix}_Chart", overlays)


def add_side_screen(prefix, side_x, center_y, center_z, size, frame_material, screen_material, accent_material, facing_right):
    width, height = size
    add_box(f"{prefix}_Frame", (side_x, center_y, center_z), (0.18, width + 0.35, height + 0.35), frame_material, bevel=0.1)
    inset_x = side_x + (0.12 if facing_right else -0.12)
    add_box(f"{prefix}_Screen", (inset_x, center_y, center_z), (0.05, width, height), screen_material, bevel=0.04)
    overlays = []
    for index, ratio in enumerate((0.72, 0.42, 0.58)):
        segment_y = center_y - width * 0.25 + index * width * 0.24
        overlays.append(add_box(
            f"{prefix}_Note_{index}",
            (inset_x + (0.03 if facing_right else -0.03), segment_y, center_z + (index - 1) * 0.42),
            (0.025, width * ratio * 0.42, 0.12),
            accent_material,
            bevel=0.02,
        ))
    join_mesh_objects(f"{prefix}_Notes", overlays)


def configure_world(background_color, strength):
    world = bpy.data.worlds.new("Vrata World")
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = color(background_color)
    background.inputs["Strength"].default_value = strength
    bpy.context.scene.world = world


def render_and_export(repo_root, scene_id, camera_location, camera_target, lens=30.0):
    release_dir = repo_root / "assets" / "scenes" / scene_id / RELEASE_VERSION
    source_dir = repo_root / "sources" / scene_id
    release_glb_path = release_dir / "scene.glb"
    tracked_release = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "--error-unmatch", str(release_glb_path.relative_to(repo_root))],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if tracked_release.returncode == 0:
        raise RuntimeError(f"published_scene_version_is_immutable:{scene_id}@{RELEASE_VERSION}")
    release_dir.mkdir(parents=True, exist_ok=True)
    source_dir.mkdir(parents=True, exist_ok=True)
    base_release_dir = repo_root / "assets" / "scenes" / scene_id / "0.1.0"
    if release_dir != base_release_dir:
        for static_name in ("scene.json", "LICENSES.md"):
            target_path = release_dir / static_name
            if not target_path.exists():
                shutil.copyfile(base_release_dir / static_name, target_path)

    camera_data = bpy.data.cameras.new("Review Camera")
    camera = bpy.data.objects.new("Review Camera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = camera_location
    camera_data.lens = lens
    camera_data.sensor_width = 36
    point_at(camera, camera_target)
    bpy.context.scene.camera = camera

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "WEBP"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "8"
    scene.render.image_settings.quality = 92
    scene.render.film_transparent = False
    scene.render.filepath = str(release_dir / "preview.webp")
    scene.render.image_settings.color_management = "FOLLOW_SCENE"
    scene.view_settings.look = "AgX - Medium High Contrast"

    bpy.ops.wm.save_as_mainfile(filepath=str(source_dir / "source.blend"))
    if not SKIP_RENDER:
        bpy.ops.render.render(write_still=True)
    bpy.ops.export_scene.gltf(
        filepath=str(release_glb_path),
        export_format="GLB",
        export_cameras=False,
        export_lights=True,
        export_tangents=True,
        export_yup=True,
        export_apply=False,
        export_image_format="AUTO",
    )


def build_personal(repo_root):
    reset_scene()
    navy = make_material("Personal Wall Navy", "#17243A", 0.78, pattern="plaster")
    midnight = make_material("Personal Midnight Trim", "#0C1524", 0.62, metallic=0.08)
    floor = make_material("Personal Smoked Oak", "#6C4935", 0.72, pattern="wood")
    floor_alt = make_material("Personal Smoked Oak Alt", "#7C5740", 0.7, pattern="wood")
    wood = make_material("Personal Warm Oak", "#B5794B", 0.58, pattern="wood", coat_weight=0.12, coat_roughness=0.32)
    cream = make_material("Personal Warm White", "#E8EEE9", 0.72, pattern="textile", sheen_weight=0.16)
    teal = make_material("Personal Teal", "#39C0AD", 0.58, pattern="textile", sheen_weight=0.2)
    blue = make_material("Personal Blue", "#4F7FEA", 0.6, pattern="textile", sheen_weight=0.2)
    amber = make_material("Personal Amber Glow", "#F5B85D", 0.38, emission="#F5B85D", emission_strength=2.4)
    screen = make_material("Personal Workspace Screen", "#DFF8F4", 0.34, emission="#9EEFE1", emission_strength=0.45, coat_weight=0.35, coat_roughness=0.18)
    rug = make_material("Personal Woven Rug", "#294A5A", 0.92, pattern="carpet", sheen_weight=0.14)
    green = make_material("Personal Plant Green", "#3D8F70", 0.85)
    clay = make_material("Personal Planter Clay", "#C96F4A", 0.82, pattern="stone")
    sky = make_material("Personal Window Sky", "#72B8D8", 0.3, emission="#72B8D8", emission_strength=0.3, coat_weight=0.5, coat_roughness=0.08)
    ceiling = make_material("Personal Ceiling Plaster", "#C9CED0", 0.88, pattern="plaster")
    brass = make_material("Personal Brushed Brass", "#B79558", 0.3, metallic=0.82)
    stone = make_material("Personal Desk Stone", "#B9B7AE", 0.5, pattern="stone", coat_weight=0.18, coat_roughness=0.3)

    add_room_shell("Personal", 10.0, 11.0, 4.2, floor, navy, midnight)
    add_box("Personal_CeilingInset", (0.0, 0.2, 4.105), (8.7, 9.6, 0.05), ceiling, bevel=0.025)
    add_box("Personal_CoveBack", (0.0, 5.14, 3.9), (8.9, 0.08, 0.08), amber, bevel=0.025)
    for x in (-4.45, 4.45):
        add_box(f"Personal_CoveSide_{x}", (x, 0.1, 3.9), (0.08, 9.8, 0.08), amber, bevel=0.025)
    for index in range(12):
        plank_material = floor_alt if index % 3 == 0 else floor
        add_box(
            f"Personal_FloorPlank_{index}",
            (-4.55 + index * 0.83, 0.0, 0.015),
            (0.76, 10.55, 0.03),
            plank_material,
            bevel=0.01,
        )
    add_box("Personal_Rug", (0.3, -0.2, 0.055), (5.8, 3.5, 0.07), rug, bevel=0.08)

    add_box("Personal_Window", (-4.77, 0.75, 2.3), (0.05, 4.2, 2.35), sky, bevel=0.03)
    for y in (-0.62, 0.75, 2.12):
        add_box(f"Personal_WindowMullion_{y}", (-4.72, y, 2.3), (0.08, 0.08, 2.38), midnight, bevel=0.02)
    add_box("Personal_WindowRail", (-4.71, 0.75, 2.3), (0.08, 4.22, 0.08), midnight, bevel=0.02)

    add_box("Personal_DeskTop", (0.55, 2.85, 0.82), (4.6, 1.25, 0.14), wood, bevel=0.08)
    for x in (-1.35, 2.45):
        add_box(f"Personal_DeskLeg_{x}", (x, 2.85, 0.41), (0.12, 0.92, 0.82), midnight, bevel=0.03)
    add_box("Personal_DeskDrawer", (1.35, 2.88, 0.68), (1.1, 0.92, 0.22), navy, bevel=0.045)
    add_box("Personal_DeskDrawerPull", (1.35, 2.28, 0.68), (0.46, 0.05, 0.045), brass, bevel=0.015)
    add_box("Personal_DeskCableTray", (0.55, 3.18, 0.58), (2.3, 0.18, 0.1), midnight, bevel=0.025)
    add_back_screen("Personal_Workspace", (0.55, 5.27, 2.35), (4.9, 2.45), midnight, screen, teal)
    add_chair("Personal_DeskChair", (-0.55, 1.55), (0.0, 1.0), (blue, midnight), width=0.78, depth=0.76)
    add_box("Personal_DeskMonitorFrame", (-0.15, 3.02, 1.52), (1.8, 0.14, 1.05), midnight, bevel=0.055)
    add_box("Personal_DeskMonitor", (-0.15, 2.92, 1.52), (1.62, 0.035, 0.87), screen, bevel=0.025)
    add_cylinder("Personal_DeskMonitorStem", (-0.15, 3.02, 1.0), 0.045, 0.38, brass, vertices=20, bevel=0.012)
    add_box("Personal_DeskMonitorBase", (-0.15, 2.96, 0.89), (0.58, 0.34, 0.05), brass, bevel=0.025)
    for index, (x, width, material) in enumerate(((-1.15, 0.38, cream), (-0.76, 0.3, teal), (1.75, 0.46, stone))):
        add_box(f"Personal_DeskAccessory_{index}", (x, 2.52, 0.93 + index * 0.025), (width, 0.4, 0.08), material, bevel=0.025)

    add_box("Personal_ShelfBody", (3.72, 3.7, 1.75), (1.5, 0.55, 3.25), midnight, bevel=0.08)
    for z in (0.65, 1.35, 2.05, 2.75):
        add_box(f"Personal_Shelf_{z}", (3.72, 3.36, z), (1.34, 0.48, 0.08), wood, bevel=0.025)
    for index, item_color in enumerate((teal, amber, cream, blue, cream, teal)):
        row = index // 3
        column = index % 3
        add_box(
            f"Personal_ShelfObject_{index}",
            (3.35 + column * 0.36, 3.03, 0.9 + row * 0.72),
            (0.2, 0.18, 0.42 + 0.08 * column),
            item_color,
            bevel=0.025,
        )

    add_chair("Personal_ReadingChair", (3.05, -0.65), (-0.75, 0.66), (teal, midnight), width=0.88, depth=0.88)
    add_cylinder("Personal_SideTable", (2.15, -0.15, 0.52), 0.42, 0.12, wood, vertices=40)
    add_cylinder("Personal_SideTableStem", (2.15, -0.15, 0.27), 0.06, 0.5, midnight, vertices=20)
    add_sphere("Personal_TableLamp", (2.15, -0.15, 0.82), (0.2, 0.2, 0.25), amber)
    add_cylinder("Personal_FloorLampStem", (3.95, -2.4, 0.9), 0.035, 1.8, brass, vertices=16, bevel=0.01)
    add_cylinder("Personal_FloorLampBase", (3.95, -2.4, 0.06), 0.34, 0.1, brass, vertices=32, bevel=0.025)
    add_sphere("Personal_FloorLampShade", (3.95, -2.4, 1.78), (0.34, 0.34, 0.28), cream)
    add_sphere("Personal_FloorLampGlow", (3.95, -2.4, 1.68), (0.13, 0.13, 0.13), amber)
    add_planter("Personal_Plant", (-3.65, 3.8, 0.0), clay, green, scale=1.1)

    for index, (y, material) in enumerate(((-2.7, cream), (-0.7, stone), (1.3, teal))):
        add_box(f"Personal_RightWallArt_{index}", (4.78, y, 2.25), (0.04, 1.25, 1.35), material, bevel=0.035)
        add_box(f"Personal_RightWallArtFrame_{index}", (4.74, y, 2.25), (0.06, 1.42, 1.52), midnight, bevel=0.04)

    for index in range(8):
        add_box(
            f"Personal_Slat_{index}",
            (-3.05 + index * 0.22, -1.8, 1.65),
            (0.09, 0.35, 3.3),
            wood if index % 2 else midnight,
            bevel=0.025,
        )
    add_box("Personal_CeilingLight", (0.4, 0.5, 3.98), (3.4, 0.13, 0.06), brass, bevel=0.02)
    for x in (-0.7, 0.4, 1.5):
        add_cylinder(f"Personal_CeilingPendant_{x}", (x, 0.5, 3.75), 0.12, 0.32, brass, vertices=24, bevel=0.025)
        add_sphere(f"Personal_CeilingPendantGlow_{x}", (x, 0.5, 3.57), (0.13, 0.13, 0.13), amber)

    configure_world("#243C52", 0.35)
    add_area_light("Personal_Key", (0.0, -1.0, 3.7), (0.5, 2.3, 1.0), 1050, "#FFE0B5", 4.0)
    add_area_light("Personal_WindowFill", (-3.7, 0.2, 2.5), (0.0, 1.5, 1.1), 850, "#A8DDF2", 3.0)
    add_area_light("Personal_ScreenFill", (0.5, 4.4, 3.0), (0.5, 1.0, 1.0), 600, "#95F2E0", 2.2)
    add_point_light("Personal_RuntimeCeiling", (0.4, 0.5, 3.55), 115, "#FFD6A0", radius=0.5, cutoff=7.5)
    add_point_light("Personal_RuntimeDesk", (0.4, 3.25, 2.6), 75, "#9DEBDF", radius=0.35, cutoff=5.0)
    add_point_light("Personal_RuntimeReading", (3.95, -2.4, 1.65), 70, "#FFD09A", radius=0.28, cutoff=4.5)
    render_and_export(repo_root, "personal-workspace-review-v1", (0.0, -4.45, 1.65), (0.35, 2.25, 1.55), lens=29.0)


def build_meeting(repo_root):
    reset_scene()
    wall = make_material("Meeting Deep Teal Wall", "#12343D", 0.8, pattern="plaster")
    trim = make_material("Meeting Graphite", "#101C22", 0.52, metallic=0.18)
    floor = make_material("Meeting Slate Floor", "#29484A", 0.82, pattern="stone")
    wood = make_material("Meeting Copper Oak", "#B8784B", 0.58, pattern="wood", coat_weight=0.16, coat_roughness=0.3)
    aqua = make_material("Meeting Aqua", "#46D6C7", 0.42, metallic=0.06)
    cyan = make_material("Meeting Cyan Light", "#84EDF0", 0.3, emission="#84EDF0", emission_strength=1.65)
    screen = make_material("Meeting Display", "#DFF8F5", 0.3, emission="#B6F3EA", emission_strength=0.42, coat_weight=0.35, coat_roughness=0.16)
    white = make_material("Meeting Soft White", "#E8F0ED", 0.78, pattern="plaster")
    chair_blue = make_material("Meeting Chair Blue", "#2B6D7C", 0.76, pattern="textile", sheen_weight=0.2)
    chair_green = make_material("Meeting Chair Green", "#367A6B", 0.76, pattern="textile", sheen_weight=0.2)
    chair_rust = make_material("Meeting Chair Rust", "#A85F48", 0.77, pattern="textile", sheen_weight=0.2)
    chair_gold = make_material("Meeting Chair Gold", "#B8954A", 0.77, pattern="textile", sheen_weight=0.2)
    green = make_material("Meeting Plant Green", "#3C8B68", 0.85)
    clay = make_material("Meeting Planter", "#B76549", 0.8, pattern="stone")
    rug = make_material("Meeting Rug", "#18333A", 0.94, pattern="carpet", sheen_weight=0.1)
    brass = make_material("Meeting Brushed Brass", "#B69B66", 0.32, metallic=0.78)
    glass = make_material("Meeting Frosted Glass", "#B9DDDA", 0.26, coat_weight=0.55, coat_roughness=0.12)

    add_room_shell("Meeting", 14.0, 13.0, 4.6, floor, wall, trim)
    add_box("Meeting_CeilingInset", (0.0, 0.2, 4.5), (12.5, 11.4, 0.06), white, bevel=0.03)
    add_box("Meeting_CeilingRecess", (0.0, 0.75, 4.44), (7.3, 5.7, 0.08), trim, bevel=0.16)
    add_box("Meeting_Rug", (0.0, 0.65, 0.04), (9.1, 6.7, 0.08), rug, bevel=0.12)
    add_cylinder("Meeting_TableTop", (0.0, 0.75, 0.83), 1.0, 0.18, wood, scale_xy=(3.25, 1.62), vertices=64, bevel=0.07)
    add_cylinder("Meeting_TableEdge", (0.0, 0.75, 0.75), 1.02, 0.08, brass, scale_xy=(3.27, 1.64), vertices=64, bevel=0.025)
    add_cylinder("Meeting_TableBase", (0.0, 0.75, 0.39), 0.72, 0.78, trim, scale_xy=(1.55, 0.9), vertices=48, bevel=0.06)
    add_cylinder("Meeting_TableCenter", (0.0, 0.75, 0.97), 0.28, 0.08, aqua, scale_xy=(1.8, 0.7), vertices=40, bevel=0.025)
    for index, (x, y) in enumerate(((-1.8, -0.05), (1.8, -0.05), (-1.8, 1.55), (1.8, 1.55))):
        add_cylinder(f"Meeting_Coaster_{index}", (x, y, 0.96), 0.16, 0.025, brass, vertices=24, bevel=0.008)
        add_cylinder(f"Meeting_Glass_{index}", (x, y, 1.08), 0.08, 0.22, glass, vertices=24, bevel=0.015)
    add_cylinder("Meeting_CenterVase", (-0.72, 0.75, 1.13), 0.14, 0.28, glass, vertices=32, bevel=0.035)
    for index, offset in enumerate(((-0.11, 0.0), (0.1, 0.05), (0.0, -0.09))):
        add_sphere(f"Meeting_CenterLeaf_{index}", (-0.72 + offset[0], 0.75 + offset[1], 1.4 + index * 0.07), (0.1, 0.065, 0.21), green)

    chairs = [
        ("Front", (0.0, -2.05), (0.0, 1.0), chair_blue),
        ("Back", (0.0, 3.55), (0.0, -1.0), chair_green),
        ("Left", (-4.0, 0.75), (1.0, 0.0), chair_rust),
        ("Right", (4.0, 0.75), (-1.0, 0.0), chair_gold),
    ]
    for label, center, facing, chair_material in chairs:
        add_chair(f"Meeting_Chair_{label}", center, facing, (chair_material, trim), width=0.82, depth=0.8)

    add_back_screen("Meeting_MainDisplay", (1.35, 6.28, 2.52), (5.7, 3.20625), trim, screen, aqua)
    add_side_screen("Meeting_CollaborationWall", -6.84, 0.5, 2.25, (4.6, 2.4), trim, white, aqua, facing_right=True)
    for index in range(7):
        add_box(
            f"Meeting_AcousticPanel_{index}",
            (-5.6 + index * 0.66, 6.18, 2.45),
            (0.48, 0.16, 3.15 if index % 2 else 2.75),
            chair_blue if index % 2 else chair_green,
            bevel=0.08,
        )

    add_box("Meeting_Credenza", (5.55, 4.65, 0.62), (2.1, 0.72, 1.1), wood, bevel=0.09)
    add_box("Meeting_CredenzaTop", (5.55, 4.65, 1.21), (2.25, 0.82, 0.08), brass, bevel=0.035)
    for index in range(3):
        add_box(f"Meeting_CredenzaDoor_{index}", (4.88 + index * 0.68, 4.24, 0.65), (0.58, 0.045, 0.82), wall, bevel=0.035)
        add_box(f"Meeting_CredenzaPull_{index}", (4.88 + index * 0.68, 4.2, 0.66), (0.18, 0.035, 0.035), brass, bevel=0.01)

    add_torus("Meeting_CeilingHalo", (0.0, 0.75, 4.08), 2.75, 0.075, cyan)
    add_cylinder("Meeting_CeilingHub", (0.0, 0.75, 4.05), 0.34, 0.12, aqua, vertices=40)
    for angle in range(0, 360, 90):
        radians = math.radians(angle)
        add_box(
            f"Meeting_CeilingSpoke_{angle}",
            (math.cos(radians) * 1.35, 0.75 + math.sin(radians) * 1.35, 4.04),
            (2.7, 0.08, 0.06),
            cyan,
            bevel=0.02,
            rotation=radians,
        )
    add_planter("Meeting_Plant_Left", (-5.8, 4.9, 0.0), clay, green, scale=1.2)
    add_planter("Meeting_Plant_Right", (5.8, 4.9, 0.0), clay, green, scale=1.2)
    for x in (-5.6, 5.6):
        add_box(f"Meeting_LightColumn_{x}", (x, 2.7, 2.2), (0.12, 0.16, 2.8), cyan, bevel=0.04)

    for y in (-4.7, -2.2, 3.8):
        add_box(f"Meeting_CeilingRail_{y}", (0.0, y, 4.37), (9.5, 0.08, 0.08), brass, bevel=0.025)
        for x in (-3.6, 0.0, 3.6):
            add_cylinder(f"Meeting_RailSpot_{x}_{y}", (x, y, 4.22), 0.095, 0.22, trim, vertices=20, bevel=0.02)

    configure_world("#173C45", 0.33)
    add_area_light("Meeting_Key", (0.0, -0.5, 4.15), (0.0, 0.8, 0.8), 1450, "#F7D7B2", 5.5)
    add_area_light("Meeting_DisplayFill", (1.0, 5.2, 3.4), (0.0, 0.3, 1.2), 920, "#9DF1E6", 3.2)
    add_area_light("Meeting_FrontFill", (0.0, -4.7, 3.2), (0.0, 0.8, 1.0), 760, "#A7DCE2", 4.0)
    for index, angle in enumerate((45, 135, 225, 315)):
        radians = math.radians(angle)
        add_point_light(
            f"Meeting_RuntimeHalo_{index}",
            (math.cos(radians) * 1.9, 0.75 + math.sin(radians) * 1.9, 3.85),
            95,
            "#D6F8EF",
            radius=0.45,
            cutoff=7.0,
        )
    add_spot_light("Meeting_RuntimeDisplay", (1.35, 4.8, 4.15), (1.35, 6.1, 2.0), 135, "#9DECE2", cutoff=6.5)
    render_and_export(repo_root, "meeting-room-review-v1", (-3.8, -5.25, 1.67), (0.25, 1.05, 1.45), lens=29.0)


def build_presentation(repo_root):
    reset_scene()
    wall = make_material("Presentation Ink Wall", "#191927", 0.82, pattern="plaster")
    trim = make_material("Presentation Black Metal", "#0B0B12", 0.45, metallic=0.25)
    floor = make_material("Presentation Charcoal Floor", "#292733", 0.88, pattern="carpet", sheen_weight=0.08)
    stage = make_material("Presentation Stage Oak", "#9B6441", 0.6, pattern="wood", coat_weight=0.15, coat_roughness=0.3)
    coral = make_material("Presentation Coral", "#D85A66", 0.7, pattern="textile", sheen_weight=0.18)
    amber = make_material("Presentation Amber", "#F3B64B", 0.35, emission="#F3B64B", emission_strength=1.8)
    cream = make_material("Presentation Screen", "#FFF0D2", 0.32, emission="#FFE1A3", emission_strength=0.42, coat_weight=0.32, coat_roughness=0.18)
    blue = make_material("Presentation Audience Blue", "#354D73", 0.8, pattern="textile", sheen_weight=0.2)
    burgundy = make_material("Presentation Audience Burgundy", "#713A4C", 0.8, pattern="textile", sheen_weight=0.2)
    purple = make_material("Presentation Audience Purple", "#59436F", 0.8, pattern="textile", sheen_weight=0.2)
    white = make_material("Presentation Soft White", "#ECE9E5", 0.78, pattern="plaster")
    brass = make_material("Presentation Brushed Brass", "#B99A5A", 0.3, metallic=0.8)
    aisle = make_material("Presentation Aisle Carpet", "#202332", 0.94, pattern="carpet")

    add_room_shell("Presentation", 16.0, 18.0, 6.0, floor, wall, trim)
    add_box("Presentation_CeilingInset", (0.0, 0.0, 5.9), (14.5, 16.3, 0.06), white, bevel=0.035)
    add_box("Presentation_CeilingRecess", (0.0, 1.0, 5.83), (11.7, 13.2, 0.08), wall, bevel=0.22)
    add_box("Presentation_CenterAisle", (0.0, -1.1, 0.025), (2.2, 12.3, 0.05), aisle, bevel=0.08)
    add_box("Presentation_Stage", (0.0, 6.45, 0.3), (12.4, 4.25, 0.6), stage, bevel=0.1)
    add_box("Presentation_StageEdge", (0.0, 4.38, 0.35), (12.1, 0.12, 0.5), brass, bevel=0.035)
    add_box("Presentation_StageGlow", (0.0, 4.3, 0.58), (11.5, 0.045, 0.07), amber, bevel=0.018)
    for index in range(3):
        add_box(
            f"Presentation_StageStep_{index}",
            (0.0, 4.55 - index * 0.34, 0.08 + index * 0.1),
            (5.0 - index * 0.35, 0.38, 0.16 + index * 0.2),
            stage,
            bevel=0.05,
        )
    add_back_screen("Presentation_MainScreen", (0.7, 8.78, 3.65), (7.733333333333333, 4.35), trim, cream, coral)
    add_box("Presentation_ProsceniumTop", (0.0, 8.55, 5.65), (13.4, 0.55, 0.38), coral, bevel=0.12)
    for x in (-6.35, 6.35):
        add_box(f"Presentation_Proscenium_{x}", (x, 8.45, 3.1), (0.48, 0.62, 4.8), coral, bevel=0.12)

    add_box("Presentation_Podium", (-4.65, 6.15, 0.92), (1.05, 0.72, 1.45), trim, bevel=0.08)
    add_box("Presentation_PodiumTop", (-4.65, 6.0, 1.68), (1.25, 0.85, 0.12), stage, bevel=0.05)
    add_box("Presentation_PodiumAccent", (-4.65, 5.6, 1.0), (0.5, 0.04, 0.65), amber, bevel=0.04)
    add_box("Presentation_PodiumDisplay", (-4.65, 5.54, 1.08), (0.38, 0.025, 0.3), cream, bevel=0.025)
    add_cylinder("Presentation_PodiumMicStem", (-4.25, 5.92, 1.94), 0.025, 0.58, brass, vertices=14, bevel=0.006)
    add_sphere("Presentation_PodiumMic", (-4.25, 5.92, 2.22), (0.065, 0.065, 0.09), trim)

    rows = [(-3.75, blue), (-1.05, burgundy), (1.65, purple)]
    seat_xs = (-4.5, -2.15, 2.15, 4.5)
    for row_index, (row_y, row_material) in enumerate(rows):
        for seat_index, x in enumerate(seat_xs):
            add_chair(
                f"Presentation_Seat_R{row_index + 1}_{seat_index + 1}",
                (x, row_y),
                (0.0, 1.0),
                (row_material, trim),
                width=0.82,
                depth=0.78,
            )

    for x in (-0.7, 0.7):
        add_box("Presentation_AisleLight_" + str(x), (x, -1.05, 0.035), (0.08, 12.5, 0.07), amber, bevel=0.02)
    for side in (-7.55, 7.55):
        for index in range(6):
            add_box(
                f"Presentation_Acoustic_{side}_{index}",
                (side, -4.8 + index * 2.05, 2.55),
                (0.12, 1.25, 3.6),
                burgundy if index % 2 else blue,
                bevel=0.08,
            )
    for side in (-7.28, 7.28):
        for index, y in enumerate((-5.5, -1.8, 1.9, 5.6)):
            add_box(f"Presentation_WallSconceBack_{side}_{index}", (side, y, 2.4), (0.1, 0.46, 0.8), brass, bevel=0.07)
            add_sphere(f"Presentation_WallSconceGlow_{side}_{index}", (side - math.copysign(0.08, side), y, 2.4), (0.1, 0.2, 0.28), amber)
    for y in (-4.2, 0.2, 4.2):
        add_box(f"Presentation_CeilingBar_{y}", (0.0, y, 5.55), (10.5, 0.16, 0.12), amber, bevel=0.04)
    for x in (-5.2, -2.6, 2.6, 5.2):
        add_cylinder(f"Presentation_Spot_{x}", (x, 4.1, 5.25), 0.18, 0.38, trim, vertices=24)
        add_sphere(f"Presentation_SpotGlow_{x}", (x, 4.0, 5.0), (0.14, 0.14, 0.16), amber)

    for index, y in enumerate((-5.0, -1.6, 1.8)):
        add_box(f"Presentation_AcousticCloud_{index}", (0.0, y, 5.55), (6.8 - index * 0.45, 1.25, 0.12), purple if index % 2 else blue, bevel=0.16)
        add_box(f"Presentation_AcousticCloudTrim_{index}", (0.0, y, 5.47), (6.45 - index * 0.45, 1.0, 0.04), brass, bevel=0.08)

    add_box("Presentation_ExitLeft", (-7.5, 7.2, 2.0), (0.08, 1.2, 2.5), white, bevel=0.06)
    add_box("Presentation_ExitRight", (7.5, 7.2, 2.0), (0.08, 1.2, 2.5), white, bevel=0.06)

    configure_world("#28233A", 0.27)
    add_area_light("Presentation_StageKey", (0.0, 4.1, 5.4), (0.0, 6.5, 0.8), 2200, "#FFD18A", 5.0)
    add_area_light("Presentation_AudienceFill", (0.0, -4.8, 4.8), (0.0, -0.5, 0.8), 1150, "#A7B9E8", 6.0)
    add_area_light("Presentation_ScreenFill", (0.8, 7.5, 4.6), (0.0, 2.0, 1.4), 1050, "#FFD79B", 4.0)
    for index, x in enumerate((-5.2, -2.6, 2.6, 5.2)):
        add_spot_light(
            f"Presentation_RuntimeStageSpot_{index}",
            (x, 4.0, 5.0),
            (x * 0.45, 6.25, 0.7),
            185,
            "#FFD49B",
            size=math.radians(48),
            cutoff=10.0,
        )
    for side in (-6.9, 6.9):
        add_point_light(f"Presentation_RuntimeWall_{side}", (side, -1.2, 2.4), 85, "#F5B875", radius=0.35, cutoff=6.0)
    add_point_light("Presentation_RuntimeAudience", (0.0, -3.8, 4.8), 105, "#AFC2EE", radius=0.65, cutoff=9.0)
    render_and_export(repo_root, "presentation-room-review-v1", (0.0, -7.4, 1.72), (0.25, 5.7, 2.25), lens=27.0)


def main():
    global RELEASE_VERSION, SKIP_RENDER
    if bpy.app.version[:3] != BLENDER_VERSION:
        raise RuntimeError(f"expected_blender_{BLENDER_VERSION}_got_{bpy.app.version[:3]}")
    args = parse_args()
    SKIP_RENDER = args.skip_render
    RELEASE_VERSION = args.version
    if not re.fullmatch(r"\d+\.\d+\.\d+", RELEASE_VERSION):
        raise RuntimeError(f"invalid_release_version:{RELEASE_VERSION}")
    repo_root = Path(args.repo_root).resolve()
    build_personal(repo_root)
    build_meeting(repo_root)
    build_presentation(repo_root)
    print(f"Built three Vrata scene candidates at {RELEASE_VERSION}.")


main()
