import requests
import json
import math

# ==========================================
# 坐标系转换工具：GCJ-02 (高德) -> WGS-84 (RTK)
# ==========================================
x_pi = 3.14159265358979324 * 3000.0 / 180.0
pi = 3.1415926535897932384626
a = 6378245.0  # 长半轴
ee = 0.00669342162296594323  # 扁率

def out_of_china(lng, lat):
    """判断是否在国内，不在国内不做偏移"""
    return not (lng > 73.66 and lng < 135.05 and lat > 3.86 and lat < 53.55)

def _transformlat(lng, lat):
    ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + \
          0.1 * lng * lat + 0.2 * math.sqrt(math.fabs(lng))
    ret += (20.0 * math.sin(6.0 * lng * pi) + 20.0 * math.sin(2.0 * lng * pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * pi) + 40.0 * math.sin(lat / 3.0 * pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * pi) + 320 * math.sin(lat * pi / 30.0)) * 2.0 / 3.0
    return ret

def _transformlng(lng, lat):
    ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + \
          0.1 * lng * lat + 0.1 * math.sqrt(math.fabs(lng))
    ret += (20.0 * math.sin(6.0 * lng * pi) + 20.0 * math.sin(2.0 * lng * pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lng * pi) + 40.0 * math.sin(lng / 3.0 * pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lng / 12.0 * pi) + 300.0 * math.sin(lng / 30.0 * pi)) * 2.0 / 3.0
    return ret

def gcj02_to_wgs84(lng, lat):
    """
    GCJ-02 坐标转换成 WGS-84 坐标
    """
    if out_of_china(lng, lat):
        return lng, lat
    dlat = _transformlat(lng - 105.0, lat - 35.0)
    dlng = _transformlng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * pi
    magic = math.sin(radlat)
    magic = 1 - ee * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * pi)
    dlng = (dlng * 180.0) / (a / sqrtmagic * math.cos(radlat) * pi)
    mglat = lat + dlat
    mglng = lng + dlng
    return [lng * 2 - mglng, lat * 2 - mglat]

# ==========================================
# 高德路径规划主逻辑
# ==========================================
def get_amap_path():
    # 1. 你的高德 Web 服务 Key
    AMAP_KEY = "ab24c47a195f096bd52f910f9ed3a14e"
    
    # 2. 设置起点和终点 (经度,纬度) 
    # 提示：用高德坐标拾取器 (https://lbs.amap.com/tools/picker) 获取真实测试点
    start_lon_lat = "120.300372,30.251569"  
    end_lon_lat = "120.298623,30.251219"    
    
    # 3. 构造骑行路径规划 API 请求 URL (V5版本)
    url = f"https://restapi.amap.com/v5/direction/bicycling?origin={start_lon_lat}&destination={end_lon_lat}&key={AMAP_KEY}&show_fields=polyline"
    
    print(f"正在向高德服务器发送请求...")
    try:
        # 发送 HTTP GET 请求
        response = requests.get(url, timeout=5.0)
        data = response.json()
        
        # 4. 解析返回的 JSON 数据
        if data.get('status') == '1':  # '1' 表示请求成功
            route = data['route']
            paths = route.get('paths', [])
            
            if paths:
                steps = paths[0].get('steps', [])
                print(f"✅ 规划成功！共找到 {len(steps)} 个路段。\n")
                
                raw_gcj02_waypoints = []
                wgs84_waypoints = []
                
                # 遍历每个路段，提取并转换经纬度
                for step in steps:
                    polyline = step.get('polyline', '')
                    points = polyline.split(';')
                    for pt in points:
                        if not pt or ',' not in pt:
                            continue

                        lon_str, lat_str = pt.split(',')
                        lon = float(lon_str)
                        lat = float(lat_str)
                        
                        # 保存原始火星坐标
                        raw_gcj02_waypoints.append((lon, lat))
                        
                        # 转换为 RTK 使用的 WGS-84 标准坐标
                        wgs_lon, wgs_lat = gcj02_to_wgs84(lon, lat)
                        wgs84_waypoints.append((wgs_lon, wgs_lat))
                
                print("-" * 50)
                print(f"提取到 {len(raw_gcj02_waypoints)} 个航点。前 3 个点对比：")
                for i in range(min(3, len(raw_gcj02_waypoints))):
                    print(f"点 {i+1}:")
                    print(f"  高德原始(GCJ-02): {raw_gcj02_waypoints[i][0]:.6f}, {raw_gcj02_waypoints[i][1]:.6f}")
                    print(f"  小车RTK(WGS-84): {wgs84_waypoints[i][0]:.6f}, {wgs84_waypoints[i][1]:.6f}")
                print("-" * 50)
                
            else:
                print("❌ 规划失败：找不到合适的路径")
        else:
            print(f"❌ API 报错：{data.get('info')}")
            
    except requests.exceptions.RequestException as e:
        print(f"网络请求发生错误，请检查网络连接: {e}")

if __name__ == '__main__':
    get_amap_path()