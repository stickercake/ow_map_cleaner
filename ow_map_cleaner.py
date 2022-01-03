# ------------------------------------------------------------------------------------ #
#                              Overwatch Map Cleaner v1.2                              #
#                                    by stickercake                                    #
#                                                                                      #
#         IMPORTANT: Click [Window] > [Toggle System Console] to see progress!         #
# ------------------------------------------------------------------------------------ #



# Merge every mesh inside [map name]_OBJECTS into a number of big ones.
# Set this to 0 if you want to keep every map object separated.
Join_Map_Mesh = 10


# If a prop without armature contains multiple meshes, merge them into one.
Join_Single_Props = True


# 0: Don't modify single-mesh props.
# 1: Reuse the same mesh/material data for identical props.
# 2: Merge each prop's vertices (& reuse the same mesh)
Optimize_Identical_Props = 2


# Keep armatures that are used for simple prop physics in Overwatch,
# such as the rotation of bucket handles and hanging lanterns.
# Shatter physics armatures will be removed regardless of this option.
Keep_Prop_Armatures = True


# Remove the spectate camera marker, etc.
Remove_Dev_Objects = True


# Fix glowing grass shaders by unlinking their emission.
Fix_Grass_Materials = True


# Log every change (replace empty with child, remove armature)
# along with the affected object to the system console.
Print_Actions = False


# If "Remove_Dev_Objects" is set to "True" and an object
# uses a texture from this list, the object will be deleted.
untextures = [
    '00000000000A', # part of spectate camera frame
    # '000000000011', # collider/missing texture
    '000000001C55', # shadow decal
    '000000006C67', # shadow decal
    '0000000044D2', # shadow decal
    '000000030373', # shadow decal
    '000000009D7C', # spectate camera
    '000000000D62', # barrier sign
    '000000000CBA', # deathmatch barrier
    '000000001B8D', # "players only, no walk, no grapple"
    '000000001BA4', # "players only"
    '000000007906', # "no turrets"
    '00000001F155', # "water"
]



import bpy
import bmesh
import datetime
import time

C = bpy.context
D = bpy.data
objects = C.scene.objects
start_seconds = time.time()

def find_map_root():
    for obj in objects:
        if not obj.parent and obj.children:
            for child in obj.children:
                if child.name.endswith('_DETAILS'):
                    return obj

root = find_map_root()
to_remove = set()
count = 0
changes = 0
obj_count = len(objects)
merge = list()
bm = bmesh.new()
mesh_joins = dict()
mats_missing = list()
blacklist = list()
broken_groups = dict()
delete_childless = ["EMPTY", "ARMATURE"]

missing_tex_name = root.name + '_BROKEN'
missing_tex = D.objects.get(missing_tex_name)
if not missing_tex:
    missing_tex = D.objects.new(missing_tex_name, None)
    missing_tex.hide_viewport = True
    collection = root.users_collection[0]
    collection.objects.link(missing_tex)
    missing_tex.parent = root

# Disconnects the emission input of node_tree's OWM shader.
def fix_grass(node_tree):
    for group in node_tree.nodes:
        if group.type == 'GROUP':
            for input in group.inputs:
                if input.name == 'Emission' and input.is_linked:
                    link = input.links[0]
                    node_tree.links.remove(input.links[0])
                    node_tree.update_tag()
                    return True
    return False

# Walks through every material to find untextures and
# broken grass shaders.
def find_untextured_mats():
    global blacklist
    mats_grass = list()

    for mat in D.materials:
        if mat.use_nodes and mat.name.startswith(root.name):
            if Remove_Dev_Objects:
                albedo = mat.node_tree.nodes.get('Albedo + AO')
                if not albedo:
                    albedo = mat.node_tree.nodes.get('Decal AO')
                    if not albedo:
                        albedo = mat.node_tree.nodes.get('Shader Normal')
                
                if albedo and albedo.image:
                    name = albedo.image.name
                    if name.startswith('000000000011'):
                        mats_missing.append(mat)
                    else:
                        for untex in untextures:
                            if name.startswith(untex):
                                blacklist.append(mat)
                                break
            
            grass = mat.node_tree.nodes.get('Grass Color + Param')
            if Fix_Grass_Materials and grass:
                if fix_grass(mat.node_tree):
                    mats_grass.append(mat)
    
    if Fix_Grass_Materials:
        print('Fixed {0} grass materials'.format(len(mats_grass)))
    if Remove_Dev_Objects:
        users = sum(mat.users for mat in blacklist)
        print('Found {0} untextured material uses'.format(users))



# Prints an action performed on obj.
def print_action(obj, name, force=False):
    if Print_Actions or force:
        print(name.ljust(9) + obj.name)

# Sets child's parent to obj's parent.
def parent_up(obj, child):
    matrixcopy = child.matrix_world.copy()
    child.parent = obj.parent
    child.matrix_world = matrixcopy


# Cleanup obj and its descendants.
# Returns whatever obj is replaced by (Object | list of Objects | None).
def clean(obj):
    children = obj.children
    childcount = len(children)
    is_armature = obj.type == 'ARMATURE'
    arm_children = []
    
    for ch in children:
        result = clean(ch)
        if result is None:
            childcount -= 1
        elif is_armature:
            vgroups = ch.vertex_groups
            groupcount = len(vgroups)
            
            # Shatter physics meshes are controlled by more than one bone
            if childcount > 1 and groupcount > 1:
                print(obj.name)
                to_remove.add(ch)
                childcount -= 1
            
            if Keep_Prop_Armatures:
                child = ch
            elif groupcount <= 1:
                parent_up(obj, ch)
                ch.modifiers.clear()
                ch.vertex_groups.clear()
                arm_children.append(ch)
                childcount -= 1
        elif type(result) is list:
            childcount += len(result) - 1
            if result:
                child = result[0]
        else:
            child = result
    
    if Keep_Prop_Armatures and is_armature and childcount == 1:
        if len(child.vertex_groups) > 1:
            count_up()
            return obj
    
    # Remove untextured meshes
    if childcount == 0 and obj.material_slots:
        mat = obj.material_slots[0].material
        if Remove_Dev_Objects and mat in blacklist:
            print_action(obj, 'DTexture')
            to_remove.add(obj)
            count_up(True)
            return None
        elif mat in mats_missing:
            print_action(obj, 'Broken')
            # Extract ID part from obj's name (Submesh_%[ID].%)
            id = obj.name
            id = id[id.find('.') + 1:]
            dot = id.rfind('.')
            if dot >= 0:
                id = id[0:dot]
            
            group = broken_groups.setdefault(id, [])
            group.append(obj)
            obj.material_slots[0].material = group[0].material_slots[0].material
            matrixcopy = obj.matrix_world.copy()
            obj.parent = missing_tex
            obj.matrix_world = matrixcopy
            count_up(True)
            return None
    
    # Join prop submeshes
    if Join_Single_Props and childcount > 1 and obj.type == 'EMPTY' and not objects_parent and not obj.name.endswith('_DETAILS'):
        merge_props = list()
        for ch in obj.children:
            if ch.type == 'MESH':
                merge_props.append(ch)
                childcount -= 1
                child = ch
        
        if len(merge_props) > 1:
            join(merge_props, joined=child)
            count_up()
            return obj
    
    # Merge the single mesh child's vertices
    elif Optimize_Identical_Props >= 1 and childcount == 1 and not objects_parent and child.type == 'MESH':
        if Optimize_Identical_Props >= 2:
            remove_doubles(child)
        else:
            reuse_mesh(child)
    
    # Remove Armatures
    if is_armature and not Keep_Prop_Armatures:
        print_action(obj, 'Physics')
        to_remove.add(obj)
        count_up(True)
        return arm_children
    
    # Remove Empties without children
    elif childcount == 0 and obj.type in delete_childless and obj != objects_parent:
        print_action(obj, 'Empty')
        to_remove.add(obj)
        count_up(True)
        return None
    
    # Remove Empties with one child (keeping its transform)
    elif childcount == 1 and obj.type == 'EMPTY':
        print_action(obj, 'Reduce')
        parent_up(obj, child)
        to_remove.add(obj)
        count_up(True)
        return child
    
    # Merge map mesh
    elif Join_Map_Mesh > 0 and objects_parent and obj.type == 'MESH':
        matrixcopy = obj.matrix_world.copy()
        obj.parent = objects_parent
        obj.matrix_world = matrixcopy
        merge.append(obj)
        count_up()
        return None
    
    count_up()
    return obj

# Increments the check object counter
def count_up(action=False):
    global count
    global changes
    
    count += 1
    if action:
        changes += 1
    
    if count % 500 == 0:
        print('Checked {0}/{1} objects ({2} changes)'.format(count, obj_count, changes))

# Merges multiple objects (obs) into one (joined).
def join(obs, joined=None, skip_reuse=False, log=True, stats=False):
    t1 = time.time()
    
    if not joined:
        joined = obs[0]
    
    if not skip_reuse and reuse_mesh(joined, obs):
        return joined
    
    if log:
        print('Joining {0} objects'.format(len(obs)))
    ctx = bpy.context.copy()
    ctx['active_object'] = joined
    ctx['selected_editable_objects'] = obs
    
    bpy.ops.object.join(ctx)
    
    t2 = time.time()
    remove_doubles(joined, skip_reuse=True, log=log)
    
    t3 = time.time()
    if stats:
        print('Join {0:.2f}s + Merge {1:.2f}s = {2:.2f}s'.format(t2-t1, t3-t2, t3-t1))
    return joined

# Reuse similar mesh if it's already registered.
def reuse_mesh(obj, obs=[]):
    name = obj.data.name
    index = name.rfind('.')
    if index >= 0:
        # [mesh name].[index]
        name = name[0:index]
    
    if name in mesh_joins:
        # Reusable mesh exists
        used = mesh_joins[name]
        if used == obj.data:
            # Reusable mesh already assigned
            return True
        
        #print('Reusing mesh ' + used.name)
        for o in obs:
            if o != obj:
                to_remove.add(o)
        
        unused = obj.data
        obj.data = mesh_joins[name]
        
        if unused.users == 0:
            D.meshes.remove(unused)
        else:
            print('Mesh {0} still has {1} users!'.format(unused.name, unused.users))
        return True
    
    mesh_joins[name] = obj.data
    return False

# Merges all vertices of obj's mesh.
def remove_doubles(obj, skip_reuse=False, log=False):
    if not skip_reuse and reuse_mesh(obj):
        return
    
    m = obj.data
    count = len(m.vertices)
    bm.from_mesh(m)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)
    bm.to_mesh(m)
    m.update()
    bm.clear()
    
    # Fix odd-looking smooth shading
    fix_merged_normals(obj)
    
    diff = count - len(m.vertices)
    if log and diff > 1000:
        print('Removed {0} vertices'.format(diff))

# Activates auto smooth normals on obj.
def fix_merged_normals(obj):
    obj.data.use_auto_smooth = True
    # obj.data.auto_smooth_angle = 1   # Given in radians
    
    ctx = C.copy()
    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            ctx['area'] = area
    ctx['object'] = obj
    ctx['active_object'] = obj
    ctx['selected_objects'] = obj
    ctx['selected_editable_objects'] = [obj]
    bpy.ops.mesh.customdata_custom_splitnormals_clear(ctx)

# Runs recursive cleaning from the top.
def clean_everything():
    global objects_parent
    global objects_parent_name
    
    for obj in root.children:
        if obj.type == 'EMPTY' and not obj == missing_tex:
            print('--- ' + obj.name)
            
            if obj.name.endswith('_OBJECTS'):
                objects_parent = obj
                objects_parent_name = obj.name
            else:
                objects_parent = None
            
            clean(obj)
        count_up()

# Deletes every object listed in to_remove.
def finish_deletions():
    count = 0
    rmv_count = len(to_remove)
    
    print('Deleting {0} objects...'.format(rmv_count))
    
    for obj in to_remove:
        if obj.users:
            obj.users_collection[0].objects.unlink(obj)
            #D.objects.remove(obj)
        count += 1
        
        if count % 1000 == 0:
            print('{:.1f}%'.format(100 * count / rmv_count))

# Returns the number of meshes with one or more users.
def count_used_meshes():
    return sum((1 if m.users else 0) for m in D.meshes)

# Splits the array a into n parts.
def split(a, n):
    k, m = divmod(len(a), n)
    return (a[i*k+min(i, m):(i+1)*k+min(i+1, m)] for i in range(n))

def run():
    print('----- Overwatch Map Cleaner -----')
    mesh_count = count_used_meshes()
    find_untextured_mats()
    clean_everything()
    finish_deletions()
    
    #print('Clearing all orphaned data-blocks without any users from the file...')
    #bpy.ops.outliner.orphans_purge(C.copy())
    
    if Join_Map_Mesh > 0 and len(merge) > Join_Map_Mesh:
        print('Joining {0} map objects...'.format(len(merge)))
        i = 0
        for merge_part in split(merge, Join_Map_Mesh):
            i += 1
            if len(merge_part) > 1:
                joined = join(merge_part, skip_reuse=True, log=False)
            elif merge_part:
                joined = merge_part[0]
            
            if joined:
                joined.name = objects_parent_name + '.' + str(i).rjust(3, '0')
            print('- Joined part {0}/{1}'.format(i, Join_Map_Mesh))
    
    print('Joining {0} broken material groups'.format(len(broken_groups)))
    for key in broken_groups:
        arr = broken_groups[key]
        if len(arr) > 1:
            join(arr, skip_reuse=True)
    
    obj_count_2 = len(objects)
    if obj_count_2 < obj_count:
        print('Reduced hierarchy object count from {0} to {1}'.format(obj_count, obj_count_2))
    
    mesh_count_2 = count_used_meshes()
    if mesh_count_2 < mesh_count:
        print('Reduced mesh count from {0} to {1}'.format(mesh_count, mesh_count_2))
    
    seconds = time.time() - start_seconds
    print('\nDone! ({0})\n'.format(str(datetime.timedelta(seconds=seconds))))
    
    if broken_groups:
        print((('There are {0} objects with broken materials located in '
                '"{1}" that need to be manually repaired/removed.'))
            .format(len(broken_groups), missing_tex_name))
    
    print('For optimal performance, save and reload the .blend file to purge all unused data-blocks.')

run()
bm.free()
