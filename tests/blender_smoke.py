import sys, importlib.util
from pathlib import Path
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('BaiGave_Plugin',root/'__init__.py',submodule_search_locations=[str(root)])
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
m.register()
print('BAIGAVE_REGISTER_OK')
from BaiGave_Plugin import backend as b
x=b.TAG_Compound({'foo':b.TAG_Int(42),'list':b.TAG_List([b.TAG_String('hello')])})
b.save_nbt(x,root/'schem'/'test.nbt')
y=b.amulet_nbt.load(str(root/'schem'/'test.nbt'))
assert y['foo'].value==42
print('BAIGAVE_NBT_OK')
block=b.Block('minecraft','stone')
assert isinstance(block,b.amulet.api.block.Block)
print('BAIGAVE_BLOCK_OK',str(block))
import bpy
from BaiGave_Plugin.codes.functions.mesh_to_mc import export_schem,create_mesh_from_dictionary
export_schem({(0,0,0):'minecraft:stone',(1,0,0):'minecraft:glass'},'integration')
p=root/'schem'/'integration.schem'
level=b.amulet.load_level(str(p))
assert str(level.get_version_block(0,0,0,'main',('java',(1,20,4)))[0]).startswith('minecraft:stone')
level.close()
print('SCHEM_READ_WRITE_OK')
result=bpy.ops.baigave.import_schem(filepath=str(p),files=[{'name':p.name}])
assert result=={'FINISHED'}
obj=bpy.data.objects.get('integration.schem')
assert obj and len(obj.data.vertices)==2, [(o.name,len(o.data.vertices)) for o in bpy.data.objects if o.type=='MESH']
assert len(bpy.data.materials)>0
print('SCHEM_IMPORT_GEOMETRY_MATERIALS_OK')
create_mesh_from_dictionary({(0,0,0):'minecraft:stone'},'direct')
assert len(bpy.data.objects['direct'].data.vertices)==1
print('DIRECT_GEOMETRY_OK')
evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
assert len(evaluated.data.vertices) == 16 and len(evaluated.data.polygons) == 12
assert bpy.data.images['stone.png'].has_data
assert bpy.data.images['glass.png'].has_data
print('NODE_EVALUATION_OK')
# Round trip a palette above the one-byte VarInt boundary.
export_schem({(i,0,0):f'test:block_{i}' for i in range(130)},'palette130')
q=b.amulet_nbt.load(str(root/'schem'/'palette130.schem'))
values=[int(v)&255 for v in q['BlockData']]
decoded=[];value=shift=0
for byte in values:
    value|=(byte&127)<<shift
    if byte&128:shift+=7
    else:decoded.append(value);value=shift=0
assert decoded==list(range(1,131)),decoded
print('PALETTE_130_OK')
# Exercise the actual structure import operator.
nbt=b.TAG_Compound({'size':b.TAG_List([b.TAG_Int(1)]*3),'entities':b.TAG_List([]),'palette':b.TAG_List([b.TAG_Compound({'Name':b.TAG_String('minecraft:stone')})]),'blocks':b.TAG_List([b.TAG_Compound({'pos':b.TAG_List([b.TAG_Int(0)]*3),'state':b.TAG_Int(0)})])})
p=root/'schem'/'structure.nbt';b.save_nbt(nbt,p)
assert bpy.ops.baigave.import_nbt(filepath=str(p),files=[{'name':p.name}])=={'FINISHED'}
assert len(bpy.data.objects['structure'].data.vertices)==1
print('NBT_IMPORT_OK')
bpy.context.scene.world_name='compat_test_world'
assert bpy.ops.baigave.create_world()=={'FINISHED'}
world=root/'saves'/'compat_test_world'
level=b.amulet.load_level(str(world))
block=b.Block('minecraft','oak_stairs',{'facing':b.TAG_String('east'),'half':b.TAG_String('bottom'),'shape':b.TAG_String('straight'),'waterlogged':b.TAG_String('false')})
level.set_version_block(0,64,0,'minecraft:overworld',('java',(1,20,4)),block)
level.save();level.close()
level=b.amulet.load_level(str(world))
assert 'oak_stairs' in str(level.get_version_block(0,64,0,'minecraft:overworld',('java',(1,20,4)))[0])
level.close()
print('WORLD_WRITE_READ_OK')
# Legacy MCEdit/WorldEdit: numeric IDs plus metadata (red wool = 35:14).
legacy = b.TAG_Compound({
    'Width': b.ShortTag(3), 'Height': b.ShortTag(1), 'Length': b.ShortTag(1),
    'Materials': b.TAG_String('Alpha'),
    'Blocks': b.ByteArrayTag([1, 20, 35]), 'Data': b.ByteArrayTag([0, 0, 14]),
    'Entities': b.TAG_List([]), 'TileEntities': b.TAG_List([]),
})
p = root / 'schem' / 'legacy.schematic'
b.save_nbt(legacy, p)
level = b.amulet.load_level(str(p))
assert str(level.get_version_block(2, 0, 0, 'main', ('java', (1,20,4)))[0]) == 'minecraft:red_wool'
level.close()
assert bpy.ops.baigave.import_schem(filepath=str(p)) == {'FINISHED'}
obj = bpy.data.objects[p.name]
assert len(obj.data.vertices) == 3
assert {tuple(v.co) for v in obj.data.vertices} == {(0,0,0),(1,0,0),(2,0,0)}
evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
assert len(evaluated.data.polygons) == 18
assert bpy.data.images['red_wool.png'].has_data
print('LEGACY_SCHEMATIC_METADATA_GEOMETRY_OK')
# Multi-select handles both formats through the same operator.
assert bpy.ops.baigave.import_schem(filepath=str(p), files=[{'name':'integration.schem'}, {'name':p.name}]) == {'FINISHED'}
print('MIXED_SCHEM_SCHEMATIC_IMPORT_OK')
m.unregister();m.register();m.unregister()
print('EXTENDED_ALL_OK')
