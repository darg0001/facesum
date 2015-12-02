import bpy
import sys
from mathutils import Vector

## import model

infile = sys.argv[sys.argv.index("--")+1]

bpy.ops.import_scene.obj(filepath=infile)


## position model

eyes = bpy.data.objects['high-poly.obj']
eye_height = (eyes.bound_box[0][1] + eyes.bound_box[3][1]) / 2

for object in bpy.context.selected_objects:
    object.location = Vector((0.15,0,-eye_height))
    object.rotation_euler.z = -0.25


## render

bpy.ops.render.render(write_still=True)
