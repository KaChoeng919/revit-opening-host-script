import clr
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *

clr.AddReference('RevitServices')
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

clr.AddReference('System.Core')
from System.Collections.Generic import List

import datetime
import os
import math

# -------------------------
# 常數與工具
# -------------------------
FEET_TO_MM = 304.8
DIST_TOL_MM = 20.0   # 幾何邊界距離比較容差（mm）- 放寬因為用邊界測距
DIST_TOL = DIST_TOL_MM / FEET_TO_MM
SHRINK_MM = 50.0     # 新增：臨時縮小邊界尺寸（mm），兩側各 SHRINK_MM/2
SHRINK = SHRINK_MM / FEET_TO_MM

def now_text():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def vec_normalize(v):
    l = v.GetLength()
    if l < 1e-9: return v
    return XYZ(v.X/l, v.Y/l, v.Z/l)

def is_horizontal_face(face):
    try:
        n = face.ComputeNormal(UV(0.5, 0.5))
        return abs(n.Z) > 0.95
    except:
        return False

def first_tangent_in_face(face):
    try:
        loops = face.GetEdgesAsCurveLoops()
        for loop in loops:
            for crv in loop:
                if isinstance(crv, Line):
                    return vec_normalize(crv.Direction)
                try:
                    p0 = crv.GetEndParameter(0)
                    p1 = crv.GetEndParameter(1)
                    pm = 0.5*(p0+p1)
                    deriv = crv.ComputeDerivatives(pm, True)
                    t = deriv.BasisX if deriv else None
                    if t and t.GetLength() > 1e-6:
                        return vec_normalize(t)
                except:
                    continue
    except:
        pass
    return XYZ.BasisX

def project_point_to_face(face, point):
    try:
        pr = face.Project(point)
        if pr:
            return pr.XYZPoint
    except:
        pass
    return None

def get_geometry_boundary_distances_to_grids(instance, grid_curve_x, grid_curve_y):
    """ 
    計算實例實際幾何邊界到兩條 Grid 的最短距離（英尺）。 
    使用 BoundingBox 的邊界點採樣，取各點到 Grid 曲線的最短距離。 
    """ 
    bb = instance.get_BoundingBox(None) 
    if not bb: 
        return None, None 
 
    # 採樣點：8個角點 + 12條邊中點 + 6個面中點，全面覆蓋幾何邊界 
    sample_points = [] 
 
    # 8個角點 
    for x in [bb.Min.X, bb.Max.X]: 
        for y in [bb.Min.Y, bb.Max.Y]: 
            for z in [bb.Min.Z, bb.Max.Z]: 
                sample_points.append(XYZ(x, y, z)) 
 
    # 12條邊中點 
    mid_x, mid_y, mid_z = (bb.Min.X + bb.Max.X)*0.5, (bb.Min.Y + bb.Max.Y)*0.5, (bb.Min.Z + bb.Max.Z)*0.5 
    edge_mids = [ 
        XYZ(mid_x, bb.Min.Y, bb.Min.Z), XYZ(mid_x, bb.Max.Y, bb.Min.Z),  # 底面X方向邊 
        XYZ(mid_x, bb.Min.Y, bb.Max.Z), XYZ(mid_x, bb.Max.Y, bb.Max.Z),  # 頂面X方向邊 
        XYZ(bb.Min.X, mid_y, bb.Min.Z), XYZ(bb.Max.X, mid_y, bb.Min.Z),  # 底面Y方向邊 
        XYZ(bb.Min.X, mid_y, bb.Max.Z), XYZ(bb.Max.X, mid_y, bb.Max.Z),  # 頂面Y方向邊 
        XYZ(bb.Min.X, bb.Min.Y, mid_z), XYZ(bb.Max.X, bb.Min.Y, mid_z),  # 前面Z方向邊 
        XYZ(bb.Min.X, bb.Max.Y, mid_z), XYZ(bb.Max.X, bb.Max.Y, mid_z),  # 後面Z方向邊 
    ] 
    sample_points.extend(edge_mids) 
 
    # 6個面中點 
    face_centers = [ 
        XYZ(mid_x, mid_y, bb.Min.Z), XYZ(mid_x, mid_y, bb.Max.Z),  # 底面、頂面 
        XYZ(mid_x, bb.Min.Y, mid_z), XYZ(mid_x, bb.Max.Y, mid_z),  # 前面、後面  
        XYZ(bb.Min.X, mid_y, mid_z), XYZ(bb.Max.X, mid_y, mid_z),  # 左面、右面 
    ] 
    sample_points.extend(face_centers) 
 
    # 計算到各 Grid 的最短距離 
    min_dist_x = None 
    min_dist_y = None 
 
    if grid_curve_x is not None: 
        distances_x = [] 
        for pt in sample_points: 
            try: 
                d = grid_curve_x.Distance(pt) 
                distances_x.append(d) 
            except: 
                continue 
        if distances_x: 
            min_dist_x = min(distances_x) 
 
    if grid_curve_y is not None: 
        distances_y = [] 
        for pt in sample_points: 
            try: 
                d = grid_curve_y.Distance(pt) 
                distances_y.append(d) 
            except: 
                continue 
        if distances_y: 
            min_dist_y = min(distances_y) 
 
    return min_dist_x, min_dist_y 

def within_tol(a, b, tol):
    if a is None or b is None:
        return False
    return abs(a - b) <= tol

def to_mm(x):
    return x * FEET_TO_MM

# -------------------------
# 主流程
# -------------------------
error_log = []
created_instances = []

doc = DocumentManager.Instance.CurrentDBDocument

# 1) 收集開口元素
try:
    collector_openings = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_GenericModel).WhereElementIsNotElementType()
    elements = [elem for elem in collector_openings
                if isinstance(elem, FamilyInstance)
                and elem.Symbol
                and "GEN-CSC-Opening-Rectangular" in elem.Symbol.Family.Name]
except Exception as e:
    error_log.append(f"{now_text()} - 收集開口時出錯: {str(e)}")
    OUT = (None, error_log)
    raise

if not elements:
    error_log.append(f"{now_text()} - 未找到任何符合條件的開口元素（族名稱包含 GEN-CSC-Opening-Rectangular）。")
    OUT = (None, error_log)
    raise ValueError("未找到任何符合條件的開口元素。")

# 2) 收集樓板
try:
    floors = list(FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Floors).WhereElementIsNotElementType())
except Exception as e:
    error_log.append(f"{now_text()} - 收集樓板時出錯: {str(e)}")
    OUT = (None, error_log)
    raise

if not floors:
    error_log.append(f"{now_text()} - 未找到任何樓板。")
    OUT = (None, error_log)
    raise ValueError("未找到任何樓板。")

# 3) 收集 Grid（X/Y 軸各一條）
grid_name_x = "13"   # X 向（橫向）參考 Grid
grid_name_y = "AA"   # Y 向（縱向）參考 Grid

grid_curve_x = None
grid_curve_y = None

try:
    grids = list(FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Grids).WhereElementIsNotElementType())
    for g in grids:
        if g.Name == grid_name_x:
            grid_curve_x = g.Curve
        elif g.Name == grid_name_y:
            grid_curve_y = g.Curve
    if grid_curve_x is None:
        error_log.append(f"{now_text()} - 警告：未找到 Grid {grid_name_x}，X 軸距離比較將被略過。")
    if grid_curve_y is None:
        error_log.append(f"{now_text()} - 警告：未找到 Grid {grid_name_y}，Y 軸距離比較將被略過。")
    if grid_curve_x is None and grid_curve_y is None:
        error_log.append(f"{now_text()} - 錯誤：判斷所需 Grid 全缺失，無法進行距離比較。")
        OUT = (None, error_log)
        raise ValueError("缺少必要 Grid。")
except Exception as e:
    error_log.append(f"{now_text()} - 收集 Grid 出錯: {str(e)}")
    OUT = (None, error_log)
    raise

# 4) 事務開始
TransactionManager.Instance.EnsureInTransaction(doc)

for element in elements:
    tnow = now_text()
    temp_instance = None
    new_instance = None
    try:
        # 已有宿主樓板則跳過
        if element.Host and isinstance(element.Host, Floor):
            error_log.append(f"{tnow} - 元素 {element.Id} 已擁有樓板宿主 (ID: {element.Host.Id})，跳過。")
            continue

        loc = element.Location
        if not isinstance(loc, LocationPoint):
            error_log.append(f"{tnow} - 元素 {element.Id} 沒有 LocationPoint。")
            continue
        p0 = loc.Point

        family_symbol = doc.GetElement(element.Symbol.Id)
        if family_symbol is None:
            error_log.append(f"{tnow} - 元素 {element.Id} 沒有有效的 FamilySymbol。")
            continue

        # 尺寸
        try:
            width  = element.LookupParameter("CSC-MEP-Width").AsDouble()
            height = element.LookupParameter("CSC-MEP-Height").AsDouble()
            depth  = element.LookupParameter("CSC-MEP-Depth").AsDouble()
        except Exception as e:
            error_log.append(f"{tnow} - 元素 {element.Id} 讀取尺寸參數出錯: {str(e)}")
            continue

        error_log.append(f"{tnow} - 元素 {element.Id} 原點(mm): X={to_mm(p0.X):.2f}, Y={to_mm(p0.Y):.2f}, Z={to_mm(p0.Z):.2f}; 尺寸(mm): W={to_mm(width):.2f}, H={to_mm(height):.2f}, D={to_mm(depth):.2f}")

        # PRE 距離（以實際幾何邊界為準）
        pre_dx, pre_dy = get_geometry_boundary_distances_to_grids(element, grid_curve_x, grid_curve_y)
        if pre_dx is not None: error_log.append(f"{tnow} - 元素 {element.Id} PRE 幾何邊界距離 X({grid_name_x})={to_mm(pre_dx):.2f}mm")
        if pre_dy is not None: error_log.append(f"{tnow} - 元素 {element.Id} PRE 幾何邊界距離 Y({grid_name_y})={to_mm(pre_dy):.2f}mm")

        # 計算臨時縮小尺寸
        temp_width = max(width - 2 * SHRINK, 0.1)
        temp_height = max(height - 2 * SHRINK, 0.1)
        error_log.append(f"{tnow} - 元素 {element.Id} 臨時縮小尺寸: W={to_mm(temp_width):.2f}mm, H={to_mm(temp_height):.2f}mm 以避邊界重疊。")

        # 4.1 臨時複本找交疊樓板
        ids = List[ElementId](); ids.Add(element.Id)
        temp_ids = ElementTransformUtils.CopyElements(doc, ids, XYZ.Zero)
        temp_instance = doc.GetElement(temp_ids[0])

        # 設定臨時尺寸
        try:
            temp_instance.LookupParameter("CSC-MEP-Width").Set(temp_width)
            temp_instance.LookupParameter("CSC-MEP-Height").Set(temp_height)
            doc.Regenerate()
        except Exception as e:
            error_log.append(f"{tnow} - 元素 {element.Id} 設定臨時尺寸失敗: {str(e)}")
            doc.Delete(temp_instance.Id)
            continue

        bb = temp_instance.get_BoundingBox(None)
        if not bb:
            error_log.append(f"{tnow} - 元素 {element.Id} 無法取得 BoundingBox。")
            doc.Delete(temp_instance.Id)
            continue

        # 擴大 BB 容差
        min_exp = bb.Min.Add(XYZ(-0.1, -0.1, -0.1))
        max_exp = bb.Max.Add(XYZ(0.1, 0.1, 0.1))
        outline = Outline(min_exp, max_exp)
        bb_filter = BoundingBoxIntersectsFilter(outline)
        potential_floors = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Floors).WherePasses(bb_filter).ToElements()

        target_face = None
        target_face_ref = None
        host_floor = None
        nearest_d = None

        for fl in potential_floors:
            try:
                inter = ElementIntersectsElementFilter(temp_instance)
                if not inter.PassesFilter(fl):
                    continue
            except:
                continue

            opt = Options(); opt.ComputeReferences = True
            geom = fl.get_Geometry(opt)
            if not geom: continue

            for go in geom:
                sd = go if isinstance(go, Solid) else None
                if not sd or not sd.Faces: continue
                for fc in sd.Faces:
                    if not fc.Reference: continue
                    if not is_horizontal_face(fc): continue
                    # 距離原點最近的水平面
                    try:
                        bbuv = fc.GetBoundingBox()
                        mid = (bbuv.Min + bbuv.Max) * 0.5
                        cxyz = fc.Evaluate(mid)
                        d = (cxyz - p0).GetLength()
                    except:
                        d = None
                    if target_face is None or (d is not None and (nearest_d is None or d < nearest_d)):
                        target_face = fc
                        target_face_ref = fc.Reference
                        host_floor = fl
                        nearest_d = d
            if target_face: break

        if not (target_face and target_face_ref and host_floor):
            error_log.append(f"{tnow} - 元素 {element.Id} 未找到可用樓板水平面。潛在樓板: {[fl.Id for fl in potential_floors]}")
            doc.Delete(temp_instance.Id)
            continue

        # 樓板厚度
        try:
            thk = host_floor.get_Parameter(BuiltInParameter.FLOOR_ATTR_THICKNESS_PARAM).AsDouble()
        except:
            thk = depth
        error_log.append(f"{tnow} - 元素 {element.Id} 宿主樓板 {host_floor.Id}，厚度={to_mm(thk):.2f}mm。")

        # 投影插入點
        p_ins = project_point_to_face(target_face, p0) or p0
        if p_ins is p0:
            error_log.append(f"{tnow} - 元素 {element.Id} 投影至面失敗，使用原點放置。")
        else:
            error_log.append(f"{tnow} - 元素 {element.Id} 投影點(mm): X={to_mm(p_ins.X):.2f}, Y={to_mm(p_ins.Y):.2f}, Z={to_mm(p_ins.Z):.2f}")

        # 获取原元素方向
        opt_orig = Options()
        geom_orig = element.get_Geometry(opt_orig)
        orig_face = None
        for go in geom_orig:
            sd = go if isinstance(go, Solid) else None
            if sd:
                for fc in sd.Faces:
                    if is_horizontal_face(fc):
                        orig_face = fc
                        break
                if orig_face: break
        orig_t_dir = first_tangent_in_face(orig_face) if orig_face else XYZ.BasisX

        # 投影到target_face平面
        n = vec_normalize(target_face.ComputeNormal(UV(0.5, 0.5)))
        proj = orig_t_dir.DotProduct(n)
        proj_t_dir = orig_t_dir.Subtract(n.Multiply(proj))
        proj_t_dir = vec_normalize(proj_t_dir)
        if proj_t_dir.GetLength() < 1e-6:
            proj_t_dir = first_tangent_in_face(target_face)
            error_log.append(f"{tnow} - 元素 {element.Id} 原方向投影失敗，使用面切向量。")
        else:
            error_log.append(f"{tnow} - 元素 {element.Id} 使用投影原方向放置。")

        t_dir = proj_t_dir
        s_dir = vec_normalize(n.CrossProduct(t_dir))
        if s_dir.GetLength() < 1e-6:
            t_dir = XYZ.BasisX if abs(n.DotProduct(XYZ.BasisX)) < 0.95 else XYZ.BasisY
            s_dir = vec_normalize(n.CrossProduct(t_dir))

        try:
            new_instance = doc.Create.NewFamilyInstance(target_face_ref, p_ins, t_dir, family_symbol)
        except Exception as e:
            error_log.append(f"{tnow} - 元素 {element.Id} 放置失敗: {str(e)}。")
            doc.Delete(temp_instance.Id)
            continue

        # 刪除臨時複本
        try: doc.Delete(temp_instance.Id)
        except: pass
        temp_instance = None

        # 設定深度
        try:
            new_instance.LookupParameter("CSC-MEP-Depth").Set(thk * 1.1)
            error_log.append(f"{tnow} - 元素 {element.Id} 設定深度={to_mm(thk*1.1):.2f}mm。")
        except Exception as e:
            error_log.append(f"{tnow} - 元素 {element.Id} 設定深度失敗: {str(e)}。")
            doc.Delete(new_instance.Id)
            continue

        # 先設置初始寬高（不互換，使用原尺寸），然後 Regenerate 以便取得幾何做 POST 測距
        try:
            new_instance.LookupParameter("CSC-MEP-Width").Set(width)
            new_instance.LookupParameter("CSC-MEP-Height").Set(height)
        except Exception as e:
            error_log.append(f"{tnow} - 元素 {element.Id} 初始設定 W/H 失敗：{str(e)}。")

        # Regenerate 以便取得實際幾何做 POST 距離
        try: doc.Regenerate()
        except: pass

        # POST 距離（以新實例的實際幾何邊界為準）
        post_dx, post_dy = get_geometry_boundary_distances_to_grids(new_instance, grid_curve_x, grid_curve_y)
        if post_dx is not None: error_log.append(f"{tnow} - 元素 {element.Id} POST 幾何邊界距離 X({grid_name_x})={to_mm(post_dx):.2f}mm")
        if post_dy is not None: error_log.append(f"{tnow} - 元素 {element.Id} POST 幾何邊界距離 Y({grid_name_y})={to_mm(post_dy):.2f}mm")

        # 互換決策（基於實際幾何邊界距離一致性）
        consistent = True
        if grid_curve_x is not None:
            if post_dx is None or pre_dx is None or not within_tol(pre_dx, post_dx, DIST_TOL):
                consistent = False
                if pre_dx is not None and post_dx is not None:
                    error_log.append(f"{tnow} - 元素 {element.Id} X軸不一致：PRE={to_mm(pre_dx):.2f}mm, POST={to_mm(post_dx):.2f}mm, 差值={to_mm(abs(pre_dx-post_dx)):.2f}mm")
        if grid_curve_y is not None:
            if post_dy is None or pre_dy is None or not within_tol(pre_dy, post_dy, DIST_TOL):
                consistent = False
                if pre_dy is not None and post_dy is not None:
                    error_log.append(f"{tnow} - 元素 {element.Id} Y軸不一致：PRE={to_mm(pre_dy):.2f}mm, POST={to_mm(post_dy):.2f}mm, 差值={to_mm(abs(pre_dy-post_dy)):.2f}mm")

        if consistent:
            # 不需互換，保持原設定
            error_log.append(f"{tnow} - 元素 {element.Id} 幾何邊界距離一致：不互換。")
        else:
            # 需要互換
            try:
                new_instance.LookupParameter("CSC-MEP-Width").Set(height)
                new_instance.LookupParameter("CSC-MEP-Height").Set(width)
                error_log.append(f"{tnow} - 元素 {element.Id} 幾何邊界距離不一致：進行互換 H->W, W->H。")
            except Exception as e:
                error_log.append(f"{tnow} - 元素 {element.Id} 互換時設定 W/H 失敗：{str(e)}。")

            # 再生並復核 POST 距離（僅記錄驗證）
            try: doc.Regenerate()
            except: pass
            try:
                post2_dx, post2_dy = get_geometry_boundary_distances_to_grids(new_instance, grid_curve_x, grid_curve_y)
                if post2_dx is not None: error_log.append(f"{tnow} - 元素 {element.Id} 互換後 POST2 幾何邊界距離 X({grid_name_x})={to_mm(post2_dx):.2f}mm")
                if post2_dy is not None: error_log.append(f"{tnow} - 元素 {element.Id} 互換後 POST2 幾何邊界距離 Y({grid_name_y})={to_mm(post2_dy):.2f}mm")
            except Exception as e:
                error_log.append(f"{tnow} - 元素 {element.Id} 互換後測距出錯：{str(e)}。")

        # 面內微調（確保插入點貼面，不影響互換決策）
        try:
            loc_fix = new_instance.Location
            if isinstance(loc_fix, LocationPoint):
                p_now = loc_fix.Point
                pr2 = target_face.Project(p_now)
                if pr2:
                    p_on = pr2.XYZPoint
                    delta = p_on.Subtract(p_now)  # 修正：使用 Subtract
                    n2 = vec_normalize(target_face.ComputeNormal(UV(0.5, 0.5)))
                    t2 = first_tangent_in_face(target_face)
                    s2 = vec_normalize(n2.CrossProduct(t2))
                    if s2.GetLength() < 1e-6:
                        t2 = XYZ.BasisX if abs(n2.DotProduct(XYZ.BasisX)) < 0.95 else XYZ.BasisY
                        s2 = vec_normalize(n2.CrossProduct(t2))
                    du = delta.DotProduct(t2)
                    dv = delta.DotProduct(s2)
                    move = t2.Multiply(du).Add(s2.Multiply(dv))
                    if move.GetLength() > 1e-6:
                        ElementTransformUtils.MoveElement(doc, new_instance.Id, move)
                        error_log.append(f"{tnow} - 元素 {element.Id} 面內微調：du={to_mm(du):.2f}mm, dv={to_mm(dv):.2f}mm。")
        except Exception as e:
            error_log.append(f"{tnow} - 元素 {element.Id} 面內微調失敗：{str(e)}。")

        # 成功：加入清單並刪除原開口
        created_instances.append(new_instance)
        try:
            doc.Delete(element.Id)
        except Exception as e:
            error_log.append(f"{tnow} - 刪除原開口 {element.Id} 失敗：{str(e)}")

    except Exception as e:
        error_log.append(f"{tnow} - 處理元素 {element.Id} 發生錯誤：{str(e)}")
        try:
            if temp_instance: doc.Delete(temp_instance.Id)
        except: pass
        try:
            if new_instance: doc.Delete(new_instance.Id)
        except: pass
        continue

# 5) 結束事務
TransactionManager.Instance.TransactionTaskDone()

# 6) 寫入日誌
log_dir = r'D:\Users\User\Desktop\test'
log_path = os.path.join(log_dir, 'error_log.txt')
try:
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    with open(log_path, 'w', encoding='utf-8') as f:
        for s in error_log:
            f.write(s + '\n')
        total = len(elements)
        succ = len(created_instances)
        fail = total - succ
        f.write(f"{now_text()} - 總結: 總開口數:{total}，成功數:{succ}，失敗數:{fail}。\n")
    error_log.append(f"{now_text()} - 日誌成功寫入至 {log_path}。")
except Exception as e:
    error_log.append(f"{now_text()} - 寫入日誌檔案時出錯: {str(e)}。")

# 輸出
OUT = (created_instances, error_log)
