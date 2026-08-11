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
    parser.add_argument(
        "--scene",
        action="append",
        choices=("personal", "personal-v2", "meeting", "presentation", "presentation-v2", "meeting-v2"),
        help="Build only the selected scene. Repeat to build multiple scenes.",
    )
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
    alpha=1.0,
):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    base_rgba = (*color(base_color)[:3], alpha)
    material.diffuse_color = base_rgba
    principled = material.node_tree.nodes.get("Principled BSDF")
    principled.inputs["Base Color"].default_value = base_rgba
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
    if alpha < 1.0:
        alpha_input = principled.inputs.get("Alpha")
        if alpha_input:
            alpha_input.default_value = alpha
        material.surface_render_method = "DITHERED"
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


def add_curve_tube(name, points, radius, material, cyclic=False):
    curve_data = bpy.data.curves.new(name=name, type="CURVE")
    curve_data.dimensions = "3D"
    curve_data.resolution_u = 3
    curve_data.bevel_depth = radius
    curve_data.bevel_resolution = 3
    spline = curve_data.splines.new("BEZIER")
    spline.bezier_points.add(len(points) - 1)
    for point, coordinates in zip(spline.bezier_points, points):
        point.co = coordinates
        point.handle_left_type = "AUTO"
        point.handle_right_type = "AUTO"
    spline.use_cyclic_u = cyclic
    obj = bpy.data.objects.new(name, curve_data)
    bpy.context.collection.objects.link(obj)
    assign_material(obj, material)
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.convert(target="MESH")
    return bpy.context.object


def add_display_panel(prefix, center, size, frame_material, screen_material):
    x, y, z = center
    width, height = size
    frame = add_box(f"{prefix}_Frame", (x, y, z), (width + 0.32, 0.18, height + 0.32), frame_material, bevel=0.08)
    screen = add_box(f"{prefix}_Screen", (x, y - 0.12, z), (width, 0.045, height), screen_material, bevel=0.035)
    return join_mesh_objects(prefix, [frame, screen])


def add_capsule_table(prefix, center, length, width, height, top_material, edge_material, base_material):
    x, y, z = center
    end_offset = (length - width) / 2
    top_parts = [
        add_box(f"{prefix}_TopCenter", (x, y, z), (length - width, width, height), top_material, bevel=0.045),
        add_cylinder(f"{prefix}_TopLeft", (x - end_offset, y, z), width / 2, height, top_material, vertices=64, bevel=0.035),
        add_cylinder(f"{prefix}_TopRight", (x + end_offset, y, z), width / 2, height, top_material, vertices=64, bevel=0.035),
    ]
    top = join_mesh_objects(f"{prefix}_Top", top_parts)
    edge_parts = [
        add_box(f"{prefix}_EdgeCenter", (x, y, z - height * 0.58), (length - width + 0.08, width + 0.08, height * 0.35), edge_material, bevel=0.025),
        add_cylinder(f"{prefix}_EdgeLeft", (x - end_offset, y, z - height * 0.58), width / 2 + 0.04, height * 0.35, edge_material, vertices=64, bevel=0.018),
        add_cylinder(f"{prefix}_EdgeRight", (x + end_offset, y, z - height * 0.58), width / 2 + 0.04, height * 0.35, edge_material, vertices=64, bevel=0.018),
    ]
    edge = join_mesh_objects(f"{prefix}_Edge", edge_parts)
    left_base = add_cylinder(f"{prefix}_BaseLeft", (x - length * 0.22, y, z / 2), 0.46, z, base_material, scale_xy=(1.35, 0.82), vertices=48, bevel=0.055)
    right_base = add_cylinder(f"{prefix}_BaseRight", (x + length * 0.22, y, z / 2), 0.46, z, base_material, scale_xy=(1.35, 0.82), vertices=48, bevel=0.055)
    return top, edge, left_base, right_base


def add_modern_chair(prefix, center, facing, upholstery, frame_material, accent_material, elevation=0.0):
    forward = Vector((facing[0], facing[1]))
    forward.normalize()
    right = Vector((forward.y, -forward.x))
    rotation = math.atan2(-forward.x, forward.y)
    x, y = center
    parts = [
        add_box(f"{prefix}_SeatShell", (x, y, elevation + 0.48), (0.82, 0.76, 0.13), frame_material, bevel=0.055, rotation=rotation),
        add_box(f"{prefix}_SeatCushion", (x, y, elevation + 0.57), (0.73, 0.67, 0.12), upholstery, bevel=0.065, rotation=rotation),
    ]
    back_xy = Vector((x, y)) - forward * 0.37
    parts.extend([
        add_box(f"{prefix}_BackShell", (back_xy.x, back_xy.y, elevation + 1.02), (0.83, 0.13, 0.9), frame_material, bevel=0.07, rotation=rotation),
        add_box(f"{prefix}_BackCushion", (back_xy.x, back_xy.y, elevation + 1.03), (0.72, 0.09, 0.69), upholstery, bevel=0.065, rotation=rotation),
        add_box(f"{prefix}_BackAccent", (back_xy.x, back_xy.y, elevation + 1.39), (0.56, 0.15, 0.055), accent_material, bevel=0.02, rotation=rotation),
    ])
    for side in (-1.0, 1.0):
        side_xy = Vector((x, y)) + right * (side * 0.32)
        parts.append(add_box(
            f"{prefix}_Leg_{side}",
            (side_xy.x, side_xy.y, elevation + 0.25),
            (0.055, 0.62, 0.5),
            frame_material,
            bevel=0.018,
            rotation=rotation,
        ))
    return join_mesh_objects(prefix, parts)


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
    scene_root = repo_root / "assets" / "scenes" / scene_id
    previous_release_dirs = sorted(
        (
            candidate
            for candidate in scene_root.iterdir()
            if candidate.is_dir()
            and candidate != release_dir
            and (candidate / "scene.json").exists()
            and re.fullmatch(r"\d+\.\d+\.\d+", candidate.name)
        ),
        key=lambda candidate: tuple(int(part) for part in candidate.name.split(".")),
        reverse=True,
    )
    for static_name in ("scene.json", "LICENSES.md"):
        target_path = release_dir / static_name
        if target_path.exists():
            continue
        if not previous_release_dirs:
            raise RuntimeError(f"missing_release_metadata:{scene_id}@{RELEASE_VERSION}:{static_name}")
        shutil.copyfile(previous_release_dirs[0] / static_name, target_path)

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


def build_personal_v2(repo_root):
    reset_scene()
    limestone = make_material("Personal V2 Limestone", "#B9AA94", 0.86, pattern="stone")
    plaster = make_material("Personal V2 Warm Plaster", "#D7D0C4", 0.91, pattern="plaster")
    charcoal = make_material("Personal V2 Charcoal", "#1A2022", 0.56, metallic=0.14)
    graphite = make_material("Personal V2 Graphite", "#30383A", 0.48, metallic=0.32)
    floor = make_material("Personal V2 Honed Floor", "#777167", 0.88, pattern="stone")
    walnut = make_material("Personal V2 Walnut", "#60412E", 0.62, pattern="wood", coat_weight=0.16, coat_roughness=0.31)
    oak = make_material("Personal V2 Natural Oak", "#A87953", 0.64, pattern="wood", coat_weight=0.14, coat_roughness=0.34)
    deep_blue = make_material("Personal V2 Deep Blue Textile", "#314B59", 0.86, pattern="textile", sheen_weight=0.18)
    rust = make_material("Personal V2 Rust Textile", "#925C48", 0.86, pattern="textile", sheen_weight=0.16)
    sand = make_material("Personal V2 Sand Textile", "#B6A48B", 0.88, pattern="textile", sheen_weight=0.16)
    rug = make_material("Personal V2 Woven Rug", "#455354", 0.96, pattern="carpet", sheen_weight=0.08)
    brass = make_material("Personal V2 Aged Brass", "#A98B59", 0.34, metallic=0.76)
    screen = make_material("Personal V2 Workspace Display", "#E4E1D7", 0.38, emission="#D5E4DF", emission_strength=0.18, coat_weight=0.22, coat_roughness=0.2)
    warm_light = make_material("Personal V2 Warm Light", "#C6A36C", 0.34, emission="#E9C88F", emission_strength=0.52)
    cool_light = make_material("Personal V2 Cool Light", "#789C9A", 0.36, emission="#B2D0CC", emission_strength=0.36)
    glass = make_material("Personal V2 Tinted Glass", "#698184", 0.22, metallic=0.06, coat_weight=0.5, coat_roughness=0.08, alpha=0.26)
    city_dark = make_material("Personal V2 Exterior", "#17252A", 0.82, emission="#17252A", emission_strength=0.14)
    city_light = make_material("Personal V2 Exterior Light", "#D6B77D", 0.42, emission="#D6B77D", emission_strength=1.25)
    green = make_material("Personal V2 Plant Green", "#486A54", 0.9)
    planter = make_material("Personal V2 Planter", "#756C62", 0.8, pattern="stone")

    add_box("PersonalV2_Floor", (0.0, 0.0, -0.1), (12.6, 12.8, 0.2), floor, bevel=0.02)
    add_box("PersonalV2_BackWall", (0.0, 6.3, 2.4), (12.6, 0.2, 4.8), plaster, bevel=0.025)
    add_box("PersonalV2_LeftWall", (-6.2, 0.0, 2.4), (0.2, 12.8, 4.8), charcoal, bevel=0.025)
    add_box("PersonalV2_Ceiling", (0.0, 0.0, 4.74), (12.6, 12.8, 0.12), charcoal, bevel=0.025)
    add_box("PersonalV2_FrontLintel", (0.0, -6.28, 4.18), (12.6, 0.22, 1.08), charcoal, bevel=0.035)
    add_box("PersonalV2_FrontLeftPier", (-5.5, -6.28, 2.05), (1.6, 0.22, 4.1), limestone, bevel=0.035)
    add_box("PersonalV2_FrontRightPier", (5.5, -6.28, 2.05), (1.6, 0.22, 4.1), limestone, bevel=0.035)
    add_box("PersonalV2_BackBaseboard", (0.0, 6.14, 0.14), (12.25, 0.1, 0.28), charcoal, bevel=0.025)
    add_box("PersonalV2_LeftBaseboard", (-6.04, 0.0, 0.14), (0.1, 12.45, 0.28), graphite, bevel=0.025)

    window_parts = []
    for index, y in enumerate((-4.8, -1.6, 1.6, 4.8)):
        window_parts.append(add_box(f"PersonalV2_Window_{index}", (6.18, y, 2.48), (0.045, 3.02, 4.35), glass, bevel=0.012))
    for y in (-6.24, -3.2, 0.0, 3.2, 6.24):
        window_parts.append(add_box(f"PersonalV2_WindowMullion_{y}", (6.14, y, 2.45), (0.11, 0.09, 4.45), charcoal, bevel=0.018))
    window_parts.extend([
        add_box("PersonalV2_WindowTop", (6.14, 0.0, 4.62), (0.11, 12.45, 0.13), charcoal, bevel=0.018),
        add_box("PersonalV2_WindowBottom", (6.14, 0.0, 0.3), (0.11, 12.45, 0.18), charcoal, bevel=0.018),
    ])
    join_mesh_objects("PersonalV2_WindowWall", window_parts)

    exterior_parts = [add_box("PersonalV2_ExteriorBackdrop", (6.85, 0.0, 2.4), (0.12, 12.4, 4.6), city_dark, bevel=0.01)]
    towers = ((-5.0, 1.25, 1.8), (-3.65, 1.8, 2.9), (-1.95, 1.4, 2.2), (-0.15, 1.95, 3.2), (1.75, 1.25, 1.9), (3.35, 1.65, 2.7), (5.0, 1.05, 1.5))
    for index, (y, z, height) in enumerate(towers):
        exterior_parts.append(add_box(f"PersonalV2_ExteriorTower_{index}", (6.7, y, z), (0.12, 0.82, height), graphite, bevel=0.025))
        for floor_index in range(max(1, int(height / 0.55))):
            exterior_parts.append(add_box(
                f"PersonalV2_ExteriorWindow_{index}_{floor_index}",
                (6.62, y, 0.52 + floor_index * 0.48),
                (0.03, 0.38, 0.11),
                city_light if (index + floor_index) % 3 == 0 else cool_light,
                bevel=0.007,
            ))
    join_mesh_objects("PersonalV2_ExteriorCity", exterior_parts)

    add_box("PersonalV2_CeilingInset", (0.25, 0.15, 4.65), (10.7, 10.95, 0.08), plaster, bevel=0.16)
    add_box("PersonalV2_CeilingIsland", (0.65, 0.5, 4.56), (7.55, 7.35, 0.12), limestone, bevel=0.22)
    ceiling_slats = []
    for index in range(11):
        ceiling_slats.append(add_box(
            f"PersonalV2_CeilingSlat_{index}",
            (-5.15 + index * 0.2, 0.9, 4.47),
            (0.085, 7.4, 0.12),
            walnut if index % 2 else oak,
            bevel=0.022,
        ))
    join_mesh_objects("PersonalV2_CeilingSlats", ceiling_slats)
    for x, y, width, depth in ((0.0, -5.45, 10.6, 0.07), (0.0, 5.46, 10.6, 0.07), (-5.55, 0.0, 0.07, 10.7)):
        add_box(f"PersonalV2_Cove_{x}_{y}", (x, y, 4.48), (width, depth, 0.055), warm_light, bevel=0.018)
    add_curve_tube(
        "PersonalV2_SculpturalLight",
        [(-2.25, -2.15, 4.25), (-0.7, -1.2, 4.19), (0.85, -1.75, 4.25), (2.55, -0.45, 4.2), (1.35, 0.9, 4.25), (-0.25, 0.15, 4.2), (-1.85, 1.2, 4.25)],
        0.062,
        warm_light,
    )
    add_curve_tube(
        "PersonalV2_TaskLight",
        [(-1.65, 2.7, 4.25), (-0.35, 2.05, 4.19), (1.15, 2.7, 4.24), (2.55, 2.0, 4.2)],
        0.045,
        cool_light,
    )

    back_feature_parts = [
        add_box("PersonalV2_BackFeatureBase", (-4.48, 6.12, 2.42), (2.95, 0.18, 4.42), walnut, bevel=0.055),
        add_box("PersonalV2_BackFeatureInset", (-4.48, 5.99, 2.42), (2.38, 0.07, 3.78), charcoal, bevel=0.12),
    ]
    for index in range(8):
        back_feature_parts.append(add_box(
            f"PersonalV2_BackFeatureSlat_{index}",
            (-5.65 + index * 0.34, 5.89 - (index % 2) * 0.025, 2.43),
            (0.16, 0.12, 3.55 - (index % 3) * 0.22),
            oak if index % 3 else walnut,
            bevel=0.035,
        ))
    join_mesh_objects("PersonalV2_BackFeature", back_feature_parts)
    add_curve_tube(
        "PersonalV2_ArchiveNiche",
        [(-5.55, 5.78, 0.55), (-5.55, 5.78, 3.15), (-5.1, 5.78, 3.82), (-4.45, 5.78, 4.02), (-3.8, 5.78, 3.82), (-3.35, 5.78, 3.15), (-3.35, 5.78, 0.55)],
        0.075,
        brass,
    )
    shelf_parts = []
    for index, z in enumerate((0.72, 1.38, 2.04, 2.7)):
        shelf_parts.append(add_box(f"PersonalV2_ArchiveShelf_{index}", (-4.45, 5.72, z), (1.82, 0.38, 0.07), oak, bevel=0.022))
    for index, (x, z, width, height, material) in enumerate(((-5.02, 0.98, 0.2, 0.42, rust), (-4.72, 1.02, 0.18, 0.5, sand), (-4.0, 1.66, 0.28, 0.48, limestone), (-4.78, 2.34, 0.42, 0.36, deep_blue), (-4.1, 2.98, 0.22, 0.45, rust))):
        shelf_parts.append(add_box(f"PersonalV2_ArchiveObject_{index}", (x, 5.49, z), (width, 0.18, height), material, bevel=0.025))
    join_mesh_objects("PersonalV2_ArchiveShelving", shelf_parts)

    add_display_panel("PersonalV2_MainDisplay", (1.45, 6.12, 2.62), (5.2, 2.6), charcoal, screen)
    credenza_parts = [
        add_box("PersonalV2_CredenzaBody", (1.45, 5.73, 0.64), (5.3, 0.68, 1.02), walnut, bevel=0.085),
        add_box("PersonalV2_CredenzaTop", (1.45, 5.68, 1.19), (5.48, 0.78, 0.09), limestone, bevel=0.04),
    ]
    for index in range(5):
        credenza_parts.extend([
            add_box(f"PersonalV2_CredenzaDoor_{index}", (-0.58 + index * 1.02, 5.34, 0.65), (0.9, 0.04, 0.72), oak if index % 2 else walnut, bevel=0.035),
            add_box(f"PersonalV2_CredenzaPull_{index}", (-0.58 + index * 1.02, 5.3, 0.69), (0.18, 0.035, 0.035), brass, bevel=0.008),
        ])
    join_mesh_objects("PersonalV2_Credenza", credenza_parts)
    add_sphere("PersonalV2_CredenzaLamp", (3.08, 5.42, 1.54), (0.25, 0.25, 0.29), warm_light)
    add_cylinder("PersonalV2_CredenzaLampStem", (3.08, 5.42, 1.34), 0.032, 0.28, brass, vertices=16, bevel=0.008)

    add_box("PersonalV2_DeskRug", (0.55, 1.55, 0.045), (6.6, 5.25, 0.08), rug, bevel=0.14)
    desk_parts = list(add_capsule_table("PersonalV2_Desk", (0.55, 2.0, 0.88), 4.85, 1.36, 0.17, oak, brass, charcoal))
    desk_parts.extend([
        add_box("PersonalV2_DeskModesty", (0.55, 2.42, 0.53), (3.4, 0.09, 0.56), walnut, bevel=0.045),
        add_box("PersonalV2_DeskReturn", (2.55, 1.18, 0.79), (0.82, 2.4, 0.12), limestone, bevel=0.07),
        add_box("PersonalV2_DeskReturnBody", (2.55, 1.34, 0.42), (0.72, 1.65, 0.72), charcoal, bevel=0.07),
        add_box("PersonalV2_DeskPower", (1.45, 2.0, 1.005), (0.58, 0.24, 0.045), graphite, bevel=0.025),
    ])
    join_mesh_objects("PersonalV2_ExecutiveDesk", desk_parts)

    monitor_parts = [
        add_box("PersonalV2_MonitorFrame", (-0.05, 2.63, 1.54), (1.72, 0.13, 1.02), charcoal, bevel=0.06),
        add_box("PersonalV2_MonitorScreen", (-0.05, 2.55, 1.54), (1.55, 0.035, 0.84), screen, bevel=0.025),
        add_cylinder("PersonalV2_MonitorStem", (-0.05, 2.63, 1.08), 0.04, 0.32, brass, vertices=18, bevel=0.01),
        add_box("PersonalV2_MonitorBase", (-0.05, 2.55, 0.94), (0.56, 0.32, 0.045), brass, bevel=0.022),
        add_box("PersonalV2_Keyboard", (-0.1, 1.72, 1.005), (0.72, 0.26, 0.035), graphite, bevel=0.025),
        add_box("PersonalV2_Notebook", (-1.35, 1.78, 1.01), (0.64, 0.42, 0.035), rust, bevel=0.025),
        add_cylinder("PersonalV2_Cup", (1.42, 1.72, 1.1), 0.075, 0.18, plaster, vertices=24, bevel=0.014),
    ]
    join_mesh_objects("PersonalV2_DeskObjects", monitor_parts)
    add_modern_chair("PersonalV2_DeskChair", (0.3, 0.86), (0.0, 1.0), deep_blue, charcoal, brass)

    lounge_parts = [
        add_box("PersonalV2_LoungePlinth", (-4.25, -0.75, 0.12), (3.15, 4.1, 0.2), limestone, bevel=0.12),
        add_box("PersonalV2_LoungeRug", (-4.18, -0.62, 0.235), (2.82, 3.75, 0.07), sand, bevel=0.14),
        add_box("PersonalV2_LoungeWallPanel", (-6.02, -0.8, 2.35), (0.12, 4.7, 3.5), deep_blue, bevel=0.08),
    ]
    for index, y in enumerate((-2.35, -1.25, -0.15, 0.95)):
        lounge_parts.append(add_box(
            f"PersonalV2_LoungeWallRelief_{index}",
            (-5.91, y, 2.32),
            (0.13 + (index % 2) * 0.06, 0.72, 2.55 + (index % 3) * 0.3),
            walnut if index % 2 else oak,
            bevel=0.055,
        ))
    join_mesh_objects("PersonalV2_LoungeArchitecture", lounge_parts)
    add_modern_chair("PersonalV2_LoungeChair", (-3.75, -0.25), (0.78, 0.62), rust, charcoal, brass)
    add_cylinder("PersonalV2_LoungeTableTop", (-2.65, 0.2, 0.56), 0.46, 0.11, limestone, vertices=48, bevel=0.04)
    add_cylinder("PersonalV2_LoungeTableStem", (-2.65, 0.2, 0.3), 0.055, 0.52, brass, vertices=18, bevel=0.012)
    add_cylinder("PersonalV2_LoungeTableBase", (-2.65, 0.2, 0.055), 0.3, 0.08, charcoal, vertices=36, bevel=0.025)
    add_sphere("PersonalV2_LoungeTableObject", (-2.65, 0.2, 0.78), (0.16, 0.16, 0.2), warm_light)

    divider_parts = []
    for index in range(9):
        divider_parts.append(add_box(
            f"PersonalV2_DividerSlat_{index}",
            (-2.5 + index * 0.18, -2.85, 1.68),
            (0.075, 0.28, 3.15 - (index % 3) * 0.22),
            walnut if index % 2 else charcoal,
            bevel=0.022,
        ))
    divider_parts.append(add_box("PersonalV2_DividerPlanter", (-1.8, -2.82, 0.42), (2.5, 0.72, 0.72), limestone, bevel=0.09))
    join_mesh_objects("PersonalV2_Divider", divider_parts)

    add_planter("PersonalV2_PlantLounge", (-5.1, -2.75, 0.23), planter, green, scale=1.22)
    add_planter("PersonalV2_PlantWindow", (5.05, 3.9, 0.0), planter, green, scale=1.18)
    add_planter("PersonalV2_PlantDivider", (-0.95, -2.8, 0.72), planter, green, scale=0.72)

    configure_world("#465054", 0.44)
    add_area_light("PersonalV2_Key", (0.0, -1.4, 4.35), (0.35, 1.6, 1.0), 1500, "#F4D8B6", 5.0)
    add_area_light("PersonalV2_WindowFill", (5.45, 0.0, 3.15), (0.2, 1.1, 1.2), 1200, "#B9D8D5", 4.3)
    add_area_light("PersonalV2_DisplayFill", (1.45, 5.3, 3.6), (1.0, 2.3, 1.2), 760, "#D5E7E2", 3.0)
    add_area_light("PersonalV2_LoungeFill", (-4.2, -0.4, 3.4), (-3.6, -0.3, 0.8), 720, "#F2CFA5", 2.8)
    for index, (x, y, light_color) in enumerate(((-1.8, -1.4, "#FFE2B5"), (0.4, -0.4, "#D5ECE7"), (2.35, -0.9, "#FFE2B5"), (-0.1, 2.4, "#D5ECE7"))):
        add_point_light(f"PersonalV2_RuntimeCeiling_{index}", (x, y, 4.03), 27, light_color, radius=0.52, cutoff=7.2)
    add_spot_light("PersonalV2_RuntimeDesk", (0.4, 2.0, 4.18), (0.35, 1.85, 0.9), 36, "#E5D6B7", cutoff=6.2)
    add_point_light("PersonalV2_RuntimeCredenza", (3.08, 5.25, 1.62), 22, "#FFD7A4", radius=0.36, cutoff=4.0)
    add_point_light("PersonalV2_RuntimeLounge", (-3.2, -0.15, 2.4), 24, "#FFD8A8", radius=0.4, cutoff=4.5)

    render_and_export(repo_root, "personal-workspace-review-v2", (0.0, -5.2, 1.76), (0.35, 1.55, 1.64), lens=27.0)


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


def build_meeting_v2(repo_root):
    reset_scene()
    limestone = make_material("Meeting V2 Warm Limestone", "#B8AA96", 0.84, pattern="stone")
    plaster = make_material("Meeting V2 Soft Plaster", "#D8D2C7", 0.9, pattern="plaster")
    charcoal = make_material("Meeting V2 Charcoal", "#171B1D", 0.56, metallic=0.12)
    graphite = make_material("Meeting V2 Graphite", "#252B2D", 0.48, metallic=0.28)
    floor = make_material("Meeting V2 Stone Floor", "#716A60", 0.86, pattern="stone")
    oak = make_material("Meeting V2 Smoked Oak", "#8D6242", 0.62, pattern="wood", coat_weight=0.13, coat_roughness=0.32)
    light_oak = make_material("Meeting V2 Light Oak", "#BA8C62", 0.6, pattern="wood", coat_weight=0.16, coat_roughness=0.28)
    walnut = make_material("Meeting V2 Walnut", "#5B3B2A", 0.58, pattern="wood", coat_weight=0.18, coat_roughness=0.3)
    sage = make_material("Meeting V2 Sage Textile", "#66776E", 0.84, pattern="textile", sheen_weight=0.18)
    clay = make_material("Meeting V2 Clay Textile", "#9A604B", 0.84, pattern="textile", sheen_weight=0.16)
    sand = make_material("Meeting V2 Sand Textile", "#B9A78D", 0.86, pattern="textile", sheen_weight=0.16)
    rug = make_material("Meeting V2 Woven Rug", "#4B5553", 0.95, pattern="carpet", sheen_weight=0.08)
    brass = make_material("Meeting V2 Aged Brass", "#A98A58", 0.35, metallic=0.74)
    screen = make_material("Meeting V2 Display", "#E7E2D6", 0.38, emission="#D8E6E2", emission_strength=0.2, coat_weight=0.22, coat_roughness=0.2)
    whiteboard = make_material("Meeting V2 Collaboration Surface", "#E4E0D6", 0.4, coat_weight=0.2, coat_roughness=0.18)
    warm_light = make_material("Meeting V2 Warm Light", "#C5A26C", 0.32, emission="#E8C78E", emission_strength=0.58)
    cool_light = make_material("Meeting V2 Cool Light", "#739C9B", 0.34, emission="#A9CECB", emission_strength=0.42)
    glass = make_material("Meeting V2 Tinted Glass", "#6B8587", 0.2, metallic=0.08, coat_weight=0.5, coat_roughness=0.08, alpha=0.28)
    city_dark = make_material("Meeting V2 Exterior", "#162329", 0.8, emission="#162329", emission_strength=0.16)
    city_light = make_material("Meeting V2 Exterior Light", "#D8B879", 0.4, emission="#D8B879", emission_strength=1.4)
    green = make_material("Meeting V2 Plant Green", "#496B55", 0.88)
    planter = make_material("Meeting V2 Planter", "#7A7065", 0.76, pattern="stone")

    add_box("MeetingV2_Floor", (0.0, 0.0, -0.1), (13.5, 12.5, 0.2), floor, bevel=0.02)
    add_box("MeetingV2_BackWall", (0.0, 6.15, 2.4), (13.5, 0.2, 4.8), limestone, bevel=0.025)
    add_box("MeetingV2_LeftWall", (-6.65, 0.0, 2.4), (0.2, 12.5, 4.8), charcoal, bevel=0.025)
    add_box("MeetingV2_Ceiling", (0.0, 0.0, 4.74), (13.5, 12.5, 0.12), plaster, bevel=0.025)
    add_box("MeetingV2_FrontLintel", (0.0, -6.12, 4.2), (13.5, 0.22, 1.05), charcoal, bevel=0.035)
    add_box("MeetingV2_FrontLeftPier", (-5.8, -6.12, 2.05), (1.7, 0.22, 4.1), limestone, bevel=0.035)
    add_box("MeetingV2_FrontRightPier", (5.8, -6.12, 2.05), (1.7, 0.22, 4.1), limestone, bevel=0.035)
    add_box("MeetingV2_BackBaseboard", (0.0, 6.0, 0.14), (13.15, 0.1, 0.28), charcoal, bevel=0.025)
    add_box("MeetingV2_LeftBaseboard", (-6.5, 0.0, 0.14), (0.1, 12.1, 0.28), graphite, bevel=0.025)

    window_parts = []
    for index, y in enumerate((-4.65, -1.55, 1.55, 4.65)):
        window_parts.append(add_box(f"MeetingV2_Window_{index}", (6.58, y, 2.48), (0.045, 2.92, 4.35), glass, bevel=0.012))
    for y in (-6.08, -3.1, 0.0, 3.1, 6.08):
        window_parts.append(add_box(f"MeetingV2_WindowMullion_{y}", (6.54, y, 2.45), (0.11, 0.09, 4.45), charcoal, bevel=0.018))
    window_parts.extend([
        add_box("MeetingV2_WindowTop", (6.54, 0.0, 4.62), (0.11, 12.15, 0.13), charcoal, bevel=0.018),
        add_box("MeetingV2_WindowBottom", (6.54, 0.0, 0.3), (0.11, 12.15, 0.18), charcoal, bevel=0.018),
    ])
    join_mesh_objects("MeetingV2_WindowWall", window_parts)

    exterior_parts = [add_box("MeetingV2_ExteriorBackdrop", (7.25, 0.0, 2.4), (0.12, 12.1, 4.6), city_dark, bevel=0.01)]
    for index, (y, z, height) in enumerate(((-4.6, 1.15, 1.6), (-3.2, 1.6, 2.5), (-1.4, 1.25, 1.8), (0.2, 1.75, 2.9), (2.1, 1.3, 2.0), (3.8, 1.8, 3.0), (5.1, 1.05, 1.4))):
        exterior_parts.append(add_box(f"MeetingV2_ExteriorTower_{index}", (7.08, y, z), (0.12, 0.92, height), graphite, bevel=0.025))
        for floor_index in range(max(1, int(height / 0.55))):
            exterior_parts.append(add_box(
                f"MeetingV2_ExteriorWindow_{index}_{floor_index}",
                (7.0, y, 0.55 + floor_index * 0.48),
                (0.03, 0.42, 0.12),
                city_light if (index + floor_index) % 3 == 0 else cool_light,
                bevel=0.008,
            ))
    join_mesh_objects("MeetingV2_ExteriorCity", exterior_parts)

    add_box("MeetingV2_CeilingInset", (0.0, 0.1, 4.65), (11.8, 10.7, 0.08), charcoal, bevel=0.14)
    add_box("MeetingV2_CeilingIsland", (0.15, 0.4, 4.57), (8.8, 6.9, 0.12), plaster, bevel=0.2)
    ceiling_slats = []
    for index in range(12):
        ceiling_slats.append(add_box(
            f"MeetingV2_CeilingSlat_{index}",
            (-5.25 + index * 0.22, 1.0, 4.48),
            (0.1, 7.8, 0.12),
            oak if index % 2 else walnut,
            bevel=0.025,
        ))
    join_mesh_objects("MeetingV2_CeilingSlats", ceiling_slats)

    add_curve_tube(
        "MeetingV2_SculpturalLight_Warm",
        [(-3.4, -2.1, 4.32), (-1.7, -0.4, 4.24), (0.0, -1.35, 4.3), (2.0, 0.25, 4.23), (3.45, -1.5, 4.3), (1.4, -2.65, 4.25), (-1.0, -2.25, 4.31)],
        0.075,
        warm_light,
        cyclic=True,
    )
    add_curve_tube(
        "MeetingV2_SculpturalLight_Cool",
        [(-2.6, 0.45, 4.31), (-1.1, 2.15, 4.24), (0.65, 1.1, 4.3), (2.8, 2.45, 4.23), (3.35, 0.55, 4.3), (1.05, -0.15, 4.24), (-0.8, 0.75, 4.3)],
        0.055,
        cool_light,
        cyclic=True,
    )

    back_panels = []
    panel_widths = (0.48, 0.62, 0.42, 0.72, 0.5, 0.66, 0.44)
    cursor_x = -5.95
    for index, panel_width in enumerate(panel_widths):
        height = 2.55 + (index % 3) * 0.32
        back_panels.append(add_box(
            f"MeetingV2_BackRelief_{index}",
            (cursor_x + panel_width / 2, 5.98 - (index % 2) * 0.045, 2.35),
            (panel_width - 0.07, 0.18 + (index % 2) * 0.09, height),
            light_oak if index % 3 else walnut,
            bevel=0.045,
        ))
        cursor_x += panel_width
    join_mesh_objects("MeetingV2_BackRelief", back_panels)
    add_box("MeetingV2_BackReliefPlinth", (-4.2, 5.83, 0.52), (3.9, 0.48, 0.72), charcoal, bevel=0.08)
    add_display_panel("MeetingV2_MainDisplay", (1.45, 6.0, 2.55), (5.6, 3.15), charcoal, screen)

    side_panel_parts = []
    for index in range(8):
        side_panel_parts.append(add_box(
            f"MeetingV2_LeftAcoustic_{index}",
            (-6.5, -3.9 + index * 1.05, 2.55),
            (0.16, 0.78, 2.75 + (index % 3) * 0.22),
            sage if index % 2 else sand,
            bevel=0.07,
        ))
    join_mesh_objects("MeetingV2_LeftAcousticWall", side_panel_parts)
    add_side_screen("MeetingV2_CollaborationWall", -6.43, 1.7, 2.32, (4.6, 2.4), graphite, whiteboard, brass, facing_right=True)

    add_box("MeetingV2_Rug", (0.0, 0.65, 0.045), (8.5, 6.2, 0.08), rug, bevel=0.14)
    add_capsule_table("MeetingV2_Table", (0.0, 0.65, 0.88), 6.0, 1.95, 0.17, light_oak, brass, charcoal)
    add_box("MeetingV2_TablePower", (0.0, 0.65, 1.005), (0.72, 0.28, 0.05), graphite, bevel=0.035)
    add_box("MeetingV2_TablePowerInset", (0.0, 0.64, 1.038), (0.38, 0.09, 0.018), cool_light, bevel=0.009)

    chairs = [
        ("FrontLeft", (-1.65, -1.15), (0.0, 1.0), clay),
        ("FrontRight", (1.65, -1.15), (0.0, 1.0), sage),
        ("BackLeft", (-1.65, 2.5), (0.0, -1.0), sage),
        ("BackRight", (1.65, 2.5), (0.0, -1.0), sand),
    ]
    for label, center, facing, upholstery in chairs:
        add_modern_chair(f"MeetingV2_Chair_{label}", center, facing, upholstery, charcoal, brass)

    table_decor = []
    for index, x in enumerate((-2.15, -0.75, 0.75, 2.15)):
        table_decor.extend([
            add_cylinder(f"MeetingV2_Cup_{index}", (x, 0.55 + (index % 2) * 0.28, 1.09), 0.075, 0.17, plaster, vertices=24, bevel=0.014),
            add_cylinder(f"MeetingV2_Coaster_{index}", (x, 0.55 + (index % 2) * 0.28, 1.008), 0.13, 0.018, brass, vertices=24, bevel=0.006),
        ])
    table_decor.extend([
        add_box("MeetingV2_Notebook", (-0.5, 0.18, 1.03), (0.62, 0.42, 0.035), clay, bevel=0.025),
        add_box("MeetingV2_Tablet", (0.6, 1.0, 1.035), (0.78, 0.48, 0.035), graphite, bevel=0.035),
    ])
    join_mesh_objects("MeetingV2_TableDecor", table_decor)

    credenza_parts = [
        add_box("MeetingV2_CredenzaBody", (4.6, 5.22, 0.68), (3.25, 0.72, 1.18), walnut, bevel=0.09),
        add_box("MeetingV2_CredenzaTop", (4.6, 5.18, 1.31), (3.42, 0.82, 0.09), limestone, bevel=0.045),
    ]
    for index in range(4):
        credenza_parts.extend([
            add_box(f"MeetingV2_CredenzaDoor_{index}", (3.45 + index * 0.77, 4.81, 0.7), (0.66, 0.04, 0.86), oak if index % 2 else light_oak, bevel=0.035),
            add_box(f"MeetingV2_CredenzaPull_{index}", (3.45 + index * 0.77, 4.77, 0.73), (0.19, 0.035, 0.035), brass, bevel=0.008),
        ])
    join_mesh_objects("MeetingV2_Credenza", credenza_parts)
    add_cylinder("MeetingV2_CredenzaVase", (3.75, 5.0, 1.52), 0.16, 0.34, planter, vertices=32, bevel=0.035)
    for index, offset in enumerate(((-0.12, 0.0), (0.1, 0.05), (0.0, -0.09))):
        add_sphere(f"MeetingV2_CredenzaLeaf_{index}", (3.75 + offset[0], 5.0 + offset[1], 1.85 + index * 0.09), (0.11, 0.06, 0.24), green)
    add_sphere("MeetingV2_CredenzaLamp", (5.35, 5.0, 1.67), (0.28, 0.28, 0.31), warm_light)
    add_cylinder("MeetingV2_CredenzaLampStem", (5.35, 5.0, 1.43), 0.035, 0.3, brass, vertices=16, bevel=0.008)

    bench_parts = [
        add_box("MeetingV2_BenchBase", (-4.75, -4.35, 0.36), (3.15, 0.92, 0.58), charcoal, bevel=0.09),
        add_box("MeetingV2_BenchSeat", (-4.75, -4.35, 0.7), (2.95, 0.84, 0.18), sand, bevel=0.08),
        add_box("MeetingV2_BenchBack", (-4.75, -4.78, 1.25), (2.95, 0.16, 1.0), sage, bevel=0.08),
        add_box("MeetingV2_BenchPillow", (-5.55, -4.58, 1.02), (0.65, 0.18, 0.54), clay, bevel=0.09),
    ]
    join_mesh_objects("MeetingV2_Bench", bench_parts)
    add_planter("MeetingV2_PlantFront", (-5.75, -2.85, 0.0), planter, green, scale=1.25)
    add_planter("MeetingV2_PlantBack", (5.55, 3.9, 0.0), planter, green, scale=1.05)

    add_box("MeetingV2_DoorFrameTop", (4.85, -5.95, 3.65), (2.4, 0.22, 0.18), charcoal, bevel=0.035)
    for x in (3.72, 5.98):
        add_box(f"MeetingV2_DoorFrame_{x}", (x, -5.95, 1.9), (0.18, 0.22, 3.55), charcoal, bevel=0.035)
    add_box("MeetingV2_Door", (4.85, -5.99, 1.85), (2.05, 0.08, 3.35), glass, bevel=0.025)
    add_box("MeetingV2_DoorHandle", (4.08, -6.08, 1.7), (0.06, 0.06, 0.62), brass, bevel=0.018)

    configure_world("#384247", 0.42)
    add_area_light("MeetingV2_Key", (0.0, -1.7, 4.35), (0.0, 0.8, 0.9), 1500, "#F4D7B4", 5.2)
    add_area_light("MeetingV2_WindowFill", (5.7, 0.2, 3.1), (0.0, 0.6, 1.1), 1150, "#B8D7D4", 4.2)
    add_area_light("MeetingV2_DisplayFill", (1.45, 5.25, 3.6), (0.0, 1.0, 1.2), 850, "#D7E9E4", 3.0)
    for index, (x, y, light_color) in enumerate(((-2.5, -1.5, "#FFE3B8"), (0.0, 0.2, "#D4ECE8"), (2.6, -1.2, "#FFE3B8"), (0.6, 2.2, "#D4ECE8"))):
        add_point_light(f"MeetingV2_RuntimeCeiling_{index}", (x, y, 4.08), 28, light_color, radius=0.55, cutoff=7.5)
    add_spot_light("MeetingV2_RuntimeDisplay", (1.45, 4.75, 4.2), (1.45, 5.9, 2.15), 38, "#D4E9E4", cutoff=6.5)
    add_point_light("MeetingV2_RuntimeCredenza", (5.35, 4.8, 1.75), 24, "#FFD6A2", radius=0.38, cutoff=4.2)

    render_and_export(repo_root, "meeting-room-review-v2", (-3.35, -5.05, 1.78), (0.35, 1.45, 1.68), lens=27.0)


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


def build_presentation_v2(repo_root):
    reset_scene()
    limestone = make_material("Presentation V2 Limestone", "#B6AA98", 0.87, pattern="stone")
    plaster = make_material("Presentation V2 Warm Plaster", "#D5CEC1", 0.92, pattern="plaster")
    charcoal = make_material("Presentation V2 Charcoal", "#171B1D", 0.57, metallic=0.12)
    graphite = make_material("Presentation V2 Graphite", "#293033", 0.48, metallic=0.3)
    carpet = make_material("Presentation V2 Auditorium Carpet", "#353D3E", 0.97, pattern="carpet", sheen_weight=0.06)
    walnut = make_material("Presentation V2 Walnut", "#5F402D", 0.62, pattern="wood", coat_weight=0.16, coat_roughness=0.31)
    oak = make_material("Presentation V2 Natural Oak", "#A37855", 0.64, pattern="wood", coat_weight=0.14, coat_roughness=0.34)
    sage = make_material("Presentation V2 Sage Textile", "#63766D", 0.87, pattern="textile", sheen_weight=0.18)
    clay = make_material("Presentation V2 Clay Textile", "#955C48", 0.87, pattern="textile", sheen_weight=0.16)
    sand = make_material("Presentation V2 Sand Textile", "#B4A289", 0.88, pattern="textile", sheen_weight=0.16)
    brass = make_material("Presentation V2 Aged Brass", "#A98A58", 0.34, metallic=0.76)
    screen = make_material("Presentation V2 Main Display", "#E5E1D7", 0.38, emission="#D9E4E0", emission_strength=0.2, coat_weight=0.22, coat_roughness=0.2)
    warm_light = make_material("Presentation V2 Warm Light", "#C7A26B", 0.34, emission="#EBC98E", emission_strength=0.6)
    cool_light = make_material("Presentation V2 Cool Light", "#789B9B", 0.36, emission="#B1CFCD", emission_strength=0.4)
    burgundy = make_material("Presentation V2 Burgundy Acoustic", "#603A42", 0.9, pattern="textile", sheen_weight=0.12)

    add_box("PresentationV2_Floor", (0.0, 0.0, -0.1), (16.2, 18.4, 0.2), carpet, bevel=0.02)
    add_box("PresentationV2_BackWall", (0.0, 9.1, 3.2), (16.2, 0.2, 6.4), plaster, bevel=0.025)
    add_box("PresentationV2_LeftWall", (-8.0, 0.0, 3.2), (0.2, 18.4, 6.4), charcoal, bevel=0.025)
    add_box("PresentationV2_RightWall", (8.0, 0.0, 3.2), (0.2, 18.4, 6.4), charcoal, bevel=0.025)
    add_box("PresentationV2_Ceiling", (0.0, 0.0, 6.34), (16.2, 18.4, 0.12), charcoal, bevel=0.025)
    add_box("PresentationV2_FrontLintel", (0.0, -9.08, 5.65), (16.2, 0.22, 1.5), limestone, bevel=0.055)
    for x in (-7.2, 7.2):
        add_box(f"PresentationV2_FrontPier_{x}", (x, -9.08, 2.65), (1.55, 0.22, 5.3), limestone, bevel=0.055)

    add_box("PresentationV2_CeilingInset", (0.0, 0.0, 6.24), (14.55, 16.7, 0.08), plaster, bevel=0.18)
    add_box("PresentationV2_CeilingRecess", (0.0, 0.55, 6.14), (11.6, 14.25, 0.12), charcoal, bevel=0.24)
    ceiling_ribs = []
    for index, y in enumerate((-6.2, -3.15, -0.1, 2.95, 6.0)):
        ceiling_ribs.extend([
            add_box(f"PresentationV2_CeilingRib_{index}", (0.0, y, 6.02), (12.7, 0.24, 0.18), walnut if index % 2 else oak, bevel=0.07),
            add_box(f"PresentationV2_CeilingRibLight_{index}", (0.0, y - 0.15, 5.92), (10.8, 0.055, 0.055), warm_light if index > 2 else cool_light, bevel=0.018),
        ])
    join_mesh_objects("PresentationV2_CeilingRhythm", ceiling_ribs)
    add_curve_tube(
        "PresentationV2_CeilingRibbonLeft",
        [(-5.4, -7.2, 5.86), (-4.25, -4.5, 5.78), (-5.0, -1.4, 5.84), (-4.1, 1.7, 5.77), (-4.75, 4.6, 5.84), (-3.85, 7.0, 5.78)],
        0.055,
        warm_light,
    )
    add_curve_tube(
        "PresentationV2_CeilingRibbonRight",
        [(5.35, -7.2, 5.86), (4.15, -4.4, 5.78), (4.95, -1.3, 5.84), (4.0, 1.8, 5.77), (4.7, 4.7, 5.84), (3.8, 7.0, 5.78)],
        0.055,
        cool_light,
    )

    for label, center_y, top_height, depth in (("Rear", -5.15, 0.6, 2.65), ("Middle", -2.15, 0.36, 2.55), ("Front", 0.78, 0.16, 2.45)):
        add_box(f"PresentationV2_{label}Tier", (0.0, center_y, top_height / 2), (13.25, depth, top_height), carpet, bevel=0.08)
        add_box(f"PresentationV2_{label}TierEdge", (0.0, center_y + depth / 2 - 0.04, top_height * 0.55), (13.1, 0.09, top_height + 0.08), brass, bevel=0.022)
    aisle_parts = [
        add_box("PresentationV2_AisleRear", (0.0, -5.15, 0.625), (1.55, 2.65, 0.05), limestone, bevel=0.055),
        add_box("PresentationV2_AisleMiddle", (0.0, -2.15, 0.385), (1.55, 2.55, 0.05), limestone, bevel=0.055),
        add_box("PresentationV2_AisleFront", (0.0, 0.78, 0.185), (1.55, 2.45, 0.05), limestone, bevel=0.055),
        add_box("PresentationV2_AisleApproach", (0.0, 2.85, 0.03), (1.55, 1.9, 0.06), limestone, bevel=0.055),
    ]
    for z, y in ((0.47, -3.8), (0.25, -0.78), (0.08, 2.05)):
        aisle_parts.append(add_box(f"PresentationV2_AisleStep_{y}", (0.0, y, z), (1.55, 0.5, 0.16), limestone, bevel=0.035))
    join_mesh_objects("PresentationV2_CenterAisle", aisle_parts)
    for x in (-0.7, 0.7):
        add_curve_tube(
            f"PresentationV2_AisleLight_{x}",
            [(x, -6.45, 0.66), (x, -3.8, 0.45), (x, -0.8, 0.24), (x, 2.7, 0.08), (x, 4.4, 0.08)],
            0.025,
            warm_light,
        )

    side_reliefs = {"Left": [], "Right": []}
    for side_name, side_x, inset_sign in (("Left", -7.88, 1.0), ("Right", 7.88, -1.0)):
        for index, y in enumerate((-6.8, -4.25, -1.7, 0.85, 3.4, 5.95)):
            side_reliefs[side_name].extend([
                add_box(
                    f"PresentationV2_{side_name}Relief_{index}",
                    (side_x + inset_sign * (0.04 + (index % 2) * 0.05), y, 3.05),
                    (0.16, 1.55, 4.35 - (index % 3) * 0.34),
                    walnut if index % 2 else oak,
                    bevel=0.07,
                ),
                add_box(
                    f"PresentationV2_{side_name}Acoustic_{index}",
                    (side_x + inset_sign * 0.14, y + 0.05, 3.0),
                    (0.08, 1.05, 3.45 - (index % 2) * 0.28),
                    burgundy if index % 2 else sage,
                    bevel=0.08,
                ),
            ])
        join_mesh_objects(f"PresentationV2_{side_name}WallRhythm", side_reliefs[side_name])
        for index, y in enumerate((-5.55, -0.45, 4.65)):
            add_box(f"PresentationV2_{side_name}SconceBack_{index}", (side_x + inset_sign * 0.2, y, 2.75), (0.08, 0.5, 0.9), brass, bevel=0.065)
            add_sphere(f"PresentationV2_{side_name}Sconce_{index}", (side_x + inset_sign * 0.29, y, 2.75), (0.1, 0.2, 0.3), warm_light)

    add_box("PresentationV2_Stage", (0.0, 6.85, 0.34), (14.2, 4.45, 0.68), oak, bevel=0.11)
    add_box("PresentationV2_StageApron", (0.0, 4.65, 0.39), (13.85, 0.18, 0.58), walnut, bevel=0.055)
    add_box("PresentationV2_StageLight", (0.0, 4.53, 0.7), (12.8, 0.055, 0.065), warm_light, bevel=0.018)
    stage_steps = []
    for index in range(3):
        stage_steps.append(add_box(
            f"PresentationV2_StageStep_{index}",
            (0.0, 4.35 - index * 0.34, 0.09 + index * 0.11),
            (4.8 - index * 0.35, 0.42, 0.18 + index * 0.2),
            limestone,
            bevel=0.055,
        ))
    join_mesh_objects("PresentationV2_StageSteps", stage_steps)

    add_box("PresentationV2_ProsceniumInset", (0.0, 8.94, 3.52), (14.35, 0.22, 5.65), charcoal, bevel=0.15)
    add_box("PresentationV2_ProsceniumTop", (0.0, 8.72, 5.95), (14.6, 0.58, 0.46), limestone, bevel=0.13)
    for x in (-6.75, 6.75):
        add_box(f"PresentationV2_ProsceniumPier_{x}", (x, 8.72, 3.35), (0.62, 0.6, 5.35), limestone, bevel=0.13)
    proscenium_fins = []
    for index in range(7):
        proscenium_fins.append(add_box(
            f"PresentationV2_ProsceniumFin_{index}",
            (-6.1 + index * 0.34, 8.47 - (index % 2) * 0.045, 3.45),
            (0.16, 0.22, 4.55 - (index % 3) * 0.35),
            walnut if index % 2 else oak,
            bevel=0.04,
        ))
    join_mesh_objects("PresentationV2_ProsceniumFins", proscenium_fins)
    add_curve_tube(
        "PresentationV2_ProsceniumArc",
        [(-6.2, 8.36, 1.0), (-6.2, 8.36, 4.85), (-5.3, 8.36, 5.6), (-3.85, 8.36, 5.82), (-2.4, 8.36, 5.62)],
        0.075,
        brass,
    )
    add_display_panel("PresentationV2_MainDisplay", (1.2, 8.65, 3.55), (8.0, 4.5), graphite, screen)

    podium_parts = [
        add_box("PresentationV2_PodiumBase", (-4.85, 6.25, 0.88), (1.15, 0.8, 1.45), charcoal, bevel=0.09),
        add_box("PresentationV2_PodiumFront", (-4.85, 5.81, 1.0), (0.82, 0.08, 1.05), walnut, bevel=0.07),
        add_box("PresentationV2_PodiumTop", (-4.85, 6.08, 1.66), (1.38, 0.92, 0.12), limestone, bevel=0.055),
        add_box("PresentationV2_PodiumDisplay", (-4.85, 5.75, 1.1), (0.5, 0.035, 0.38), screen, bevel=0.035),
        add_box("PresentationV2_PodiumAccent", (-4.85, 5.68, 0.61), (0.42, 0.035, 0.055), warm_light, bevel=0.014),
        add_cylinder("PresentationV2_PodiumMicStem", (-4.42, 6.05, 1.95), 0.024, 0.56, brass, vertices=14, bevel=0.006),
        add_sphere("PresentationV2_PodiumMic", (-4.42, 6.05, 2.22), (0.065, 0.065, 0.09), charcoal),
    ]
    join_mesh_objects("PresentationV2_Podium", podium_parts)
    add_box("PresentationV2_StageBench", (4.75, 7.0, 0.82), (2.45, 0.82, 0.24), sand, bevel=0.1)
    add_box("PresentationV2_StageBenchBase", (4.75, 7.0, 0.47), (2.2, 0.64, 0.65), walnut, bevel=0.08)

    rows = [
        ("Rear", -5.0, 0.6, (clay, sage, sage, clay)),
        ("Middle", -2.0, 0.36, (sage, sand, sand, sage)),
        ("Front", 0.95, 0.16, (sand, clay, clay, sand)),
    ]
    seat_xs = (-5.15, -2.45, 2.45, 5.15)
    for row_name, row_y, elevation, upholstery_set in rows:
        for seat_index, (x, upholstery) in enumerate(zip(seat_xs, upholstery_set), start=1):
            add_modern_chair(
                f"PresentationV2_Seat_{row_name}_{seat_index}",
                (x, row_y),
                (0.0, 1.0),
                upholstery,
                charcoal,
                brass,
                elevation=elevation,
            )

    for side_name, x in (("Left", -6.9), ("Right", 6.9)):
        add_box(f"PresentationV2_Exit_{side_name}", (x, -7.72, 1.88), (1.45, 0.16, 3.55), graphite, bevel=0.08)
        add_box(f"PresentationV2_ExitFrame_{side_name}", (x, -7.62, 1.9), (1.72, 0.12, 3.82), brass, bevel=0.075)
        add_box(f"PresentationV2_ExitHandle_{side_name}", (x + (-0.42 if x < 0 else 0.42), -7.5, 1.65), (0.06, 0.06, 0.62), brass, bevel=0.018)

    configure_world("#3D4346", 0.4)
    add_area_light("PresentationV2_StageKey", (0.0, 4.1, 5.75), (0.4, 6.5, 1.0), 2150, "#F5D3A5", 5.5)
    add_area_light("PresentationV2_AudienceFill", (0.0, -5.6, 5.25), (0.0, -0.5, 0.8), 1250, "#B5CDCF", 6.0)
    add_area_light("PresentationV2_ScreenFill", (1.2, 7.65, 4.85), (0.8, 4.5, 1.4), 950, "#D6E7E2", 4.0)
    for index, x in enumerate((-4.8, -1.6, 1.6, 4.8)):
        add_spot_light(
            f"PresentationV2_RuntimeStageSpot_{index}",
            (x, 4.15, 5.7),
            (x * 0.55, 6.65, 0.75),
            44,
            "#FFD8A5",
            size=math.radians(48),
            cutoff=10.5,
        )
    for index, (x, y) in enumerate(((-5.8, -4.8), (5.8, -4.8), (-5.8, 0.2), (5.8, 0.2))):
        add_point_light(f"PresentationV2_RuntimeAudience_{index}", (x, y, 3.55), 26, "#C5DCDD", radius=0.48, cutoff=7.2)
    add_point_light("PresentationV2_RuntimePodium", (-4.7, 5.7, 2.7), 24, "#FFD6A2", radius=0.38, cutoff=4.5)

    render_and_export(repo_root, "presentation-room-review-v2", (0.0, -7.65, 2.2), (0.35, 6.1, 2.35), lens=27.0)


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
    builders = {
        "personal": build_personal,
        "personal-v2": build_personal_v2,
        "meeting": build_meeting,
        "presentation": build_presentation,
        "presentation-v2": build_presentation_v2,
        "meeting-v2": build_meeting_v2,
    }
    selected_scenes = args.scene or ("personal", "meeting", "presentation")
    for scene_name in selected_scenes:
        builders[scene_name](repo_root)
    print(f"Built {', '.join(selected_scenes)} Vrata scene candidate(s) at {RELEASE_VERSION}.")


main()
