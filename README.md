# GTA 10,000 人实时位置与行为模拟器

这是一个面向大多伦多地区（GTA）的合成人口移动模拟项目。系统使用 10,000 名成年合成人物、真实 OpenStreetMap 地点、固定人物关系和可调行为规则，在任意时间点实时计算每个人的位置与状态。

当前地点池覆盖 Toronto、North York、Scarborough、Brampton、Markham、Vaughan、Richmond Hill 一带；人物住宅目前只分配在 **Markham** 和 **Scarborough**。

## 核心模型

系统的基本流程是：

```text
当前时间 → 行为日程 → 地点选择 → 直线移动 → 实时位置
```

- 不预先保存 10,000 人每分钟的 GPS 记录。
- API 收到查询后，根据当前时钟、正在进行的事件和路线实时计算位置。
- 默认模拟速度为 `1.0`，即现实 1 秒对应模拟 1 秒；管理员可暂停、跳转或加速。
- 日程以一天为滚动窗口生成，服务跨日后自动补充下一天。
- HOME、WORK 和组织归属是固定绑定；餐厅、咖啡馆、商场等活动地点从真实 OSM POI 中选择。
- 默认使用起点和终点之间的直线移动，不加载道路图或生成路线缓存。设置 `ROUTING_MODE=road` 后可恢复本地 OSM 道路图 A* 路由。

## 人物、地点与关系

主要数据文件：

- `data/gta_synthetic_population_10000.csv`：原始 10,000 人合成人口。
- `data/gta_population_with_places.csv`：加入 HOME、WORK、`employer_id` 和性格字段的运行时人物表。
- `data/places.csv`：494,877 个真实 OSM 地点的生成源，包括住宅、办公、餐饮、零售、医疗、公园等。
- `data/places.sqlite`：API 使用的预生成只读地点库，含 R-Tree 空间索引；固定地点按需读取，只把 36,603 个活动 POI 放入轻量内存网格。
- `data/person_places.csv`：人物与 HOME、WORK 等固定地点的绑定。
- `data/organizations.csv`：一次性解析并缓存的雇主目录。优先使用 OSM 真实名称；`is_real_name`、`name_source`、匹配距离、来源链接和说明用于区分直接命名、附近 POI 匹配和未解析地点。
- `data/person_organizations.csv`：人物的雇主、团队、原始工作地点和名称匹配可信度。多个公司可以映射到同一工作建筑，人物表通过 `employer_id` 引用组织。
- `data/relationships.csv`：样本内家人、伴侣、同事、朋友、邻居等关系；末列 `relationship_context` 结合双方人物属性、性格与相关地点，提供可直接用于 AI 提示词的具体中文关系背景。
- `data/external_contacts.csv`：不属于这 10,000 人的轻量级样本外联系人。
- `data/person_behavior_profiles.csv`：连续性格参数、沟通风格和可直接用于 AI 提示词的中文人物描述。

地点先于关系生成。人物不要求以完整家庭为单位进入样本，因此母亲可能在表内、父亲可能不在表内。默认约 30% 的人物至少拥有一条样本内家庭关系；夫妻共享住宅，成年子女、父母、兄弟姐妹和其他亲属不强制同住。

同事关系来自共同组织或团队；朋友、邻居和室友关系会参考已经分配好的地点与人物属性。约会、朋友外出、拜访朋友和探亲会检查双方空闲时间，并为样本内双方生成同步事件。拜访朋友会使用对方真实 HOME，外出活动会选择真实 POI。

公司名称只在数据生成阶段从本地 OSM 地点池解析一次。实时位置请求不会调用 Google、OSM 或其他公司查询服务；没有可靠名称的地点会明确标记为 `Unidentified ...`，不会伪造公司名。

当前活动地点同样来自这份 OSM 快照，而不是随机经纬度。地点池包含 8,340 个餐厅、1,922 个咖啡馆、690 个酒吧/酒馆/夜店、682 个健身或体育中心、29 个电影院、2,432 个公园、627 个超市、18,312 个其他零售地点、885 个医疗地点和 858 个药房。其中餐饮、酒吧、咖啡馆、健身/体育中心等超过 95% 带可读名称或地址；没有名称的对象仍保留真实 OSM 坐标和 ID。如果首选半径内没有候选，系统会使用该类别最近的真实 OSM 地点，而不是生成一个活动坐标。当前 `gym` 只覆盖 `fitness_centre` 和 `sports_centre`，尚未完整纳入 stadium、arena、pitch、ice rink 等大型或专项体育设施。

## 本地运行

需要 Python 3.11 或更高版本：

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m simulator.cli world --time 2026-08-24T18:30:00 --compact
python -m simulator.cli benchmark --time 2026-08-24T18:30:00
```

启动 API：

```bash
set ADMIN_API_KEY=replace-with-a-long-random-secret
uvicorn simulator.api:app --host 0.0.0.0 --port 8000 --workers 1
```

macOS 或 Linux 请使用：

```bash
export ADMIN_API_KEY=replace-with-a-long-random-secret
```

常用接口：

- `GET /health`
- `GET /api/v1/simulation`
- `GET /api/v1/world?compact=true`
- `GET /api/v1/world?bbox=-80.15,43.35,-78.65,44.05`
- `GET /api/v1/people/P00001/location`
- `GET /api/v1/organizations`
- `GET /api/v1/people/P00001/organization`

`/api/v1/world` 一次返回当前 10,000 人的位置。`compact=true` 使用紧凑数组格式；可通过 `bbox` 只请求地图视野内的人物。
`/api/v1/organizations` 返回静态组织目录和人物归属，适合第二个项目启动时获取一次并缓存；公司名不会重复塞入每三分钟的位置快照。

## 行为管理界面

打开 `/admin`，使用 HTTP Basic 登录：

- 用户名：环境变量 `ADMIN_USER`，默认 `admin`
- 密码：`ADMIN_API_KEY`

页面可以调整：

- 工作日、周末和服务业上班概率
- 晚间活动权重
- 约会、朋友和家庭活动接受率
- 社交取消率、时间粒度和每日联动上限
- 模拟时钟、暂停、跳转与速度
- 日程重新生成
- 新增人物并自动分配真实 HOME、WORK 和需要的 SCHOOL 地点
- 临时指定某个人在一段时间内的位置和状态

管理员新增的人物会立即进入实时位置结果，只生成该人物的当日日程，并保存在 Railway Volume 的状态文件中，重启后不会丢失。新增人物默认还没有关系；其自动分配的雇主会进入运行时组织查询。高级 JSON 编辑仍保留，方便备份和批量修改。

## 从 OSM 重新生成数据

仓库已包含 BBBike 导出的 `data/gta-mobility.osm.pbf` 和由其生成的 `data/road_network.pkl`。需要使用更新的 OSM 快照重建全部地点和人物绑定时，可以替换 PBF 后执行：

```bash
python scripts/extract_pbf_places.py
python scripts/build_places_db.py
python scripts/build_road_network.py
python scripts/assign_places.py
python scripts/generate_personality_profiles.py
python scripts/validate_personality_profiles.py
python scripts/validate_places.py
python scripts/generate_relationships.py
python scripts/validate_relationships.py
python scripts/generate_external_contacts.py
```

`data/road_network.pkl` 是保留备用的本地可驾驶道路图，已经随仓库发布。默认直线模式不会加载它；启用 `ROUTING_MODE=road` 后，按需生成的路线缓存保存在 `work/routes.sqlite`，不会进入 Git 历史。

`build_places_db.py` 在数据生成阶段把 CSV 转为预索引的 `data/places.sqlite`。部署启动时直接打开数据库，不会重新转换；CSV 保留在仓库中用于检查和重建，但通过 `.dockerignore` 排除在 Railway 镜像之外。

`generate_relationships.py` 同时重建组织目录、人物雇主绑定和同事关系，并把稳定的 `employer_id` 合并回运行时人物表。组织名称来自本地 `places.csv`，因此该步骤不产生运行时外部 API 费用。

## Railway 部署

仓库包含 `Dockerfile` 和 `railway.json`。在 Railway 中：

1. 创建 Service 并连接 GitHub 仓库 `wias94/location`。
2. 选择 `main` 分支并开启 Autodeploy。
3. 设置不少于 16 个字符的 `ADMIN_API_KEY`。
4. 如需保护公共 API，设置 `PUBLIC_API_KEY`。
5. 挂载持久化 Volume 到 `/data`。
6. 在 Networking 中生成公开域名。
7. 暂时保持一个 replica 和一个 worker。

推送到 `main` 后，只要 Autodeploy 已开启，Railway 会自动构建并部署新提交。`/health` 是部署健康检查地址。

Railway 默认使用直线模式，因此不会把 `data/road_network.pkl` 展开到内存，也不会运行后台 A* 预热或生成路线缓存。真实 HOME、WORK、活动 POI 和地点名称不受影响。以后在 Railway 增加 `ROUTING_MODE=road` 并重新部署，即可恢复 GTA 道路路线。

## 环境变量

- `ADMIN_API_KEY`：生产环境必填，至少 16 个字符。
- `ADMIN_USER`：管理界面用户名，默认 `admin`。
- `PUBLIC_API_KEY`：可选；启用后客户端通过 `X-API-Key` 发送。
- `STATE_PATH`：时钟、行为配置、临时交互和管理员新增人物，Railway 默认 `/data/simulator-state.json`。
- `SIMULATION_START`：初始模拟时间。
- `SCHEDULE_DAYS`：滚动日程窗口，默认 `1`。
- `CORS_ORIGINS`：允许访问 API 的来源，逗号分隔。
- `POPULATION_PATH`：默认 `data/gta_population_with_places.csv`。
- `PLACES_PATH`：默认优先使用 `data/places.sqlite`；数据库不存在时回退到 `data/places.csv`。
- `RELATIONSHIPS_PATH`：默认 `data/relationships.csv`。
- `ORGANIZATIONS_PATH`：默认 `data/organizations.csv`。
- `PERSON_ORGANIZATIONS_PATH`：默认 `data/person_organizations.csv`。
- `EXTERNAL_CONTACTS_PATH`：默认 `data/external_contacts.csv`。
- `ROAD_NETWORK_PATH`：默认 `data/road_network.pkl`。
- `ROUTE_CACHE_PATH`：默认 `work/routes.sqlite`。
- `ROUTING_MODE`：默认 `straight`；设置为 `road` 可重新启用保留的 OSM A* 道路导航。

## 代码结构

- `simulator/behavior.py`：从人物属性、性格和模板生成行为日程。
- `simulator/places.py`：固定地点、真实活动 POI 和关系地点解析。
- `simulator/social.py`：双方时间协调和同步社交事件。
- `simulator/routes.py`：路线估算、OSM 道路图搜索和 SQLite 缓存。
- `simulator/world.py`：任意时间点的位置插值和批量世界快照。
- `simulator/service.py`：实时服务、滚动日程、缓存与状态持久化。
- `simulator/api.py`：FastAPI 公共接口和管理接口。
- `simulator/admin.html`：行为逻辑可视化编辑器。

所有随机流均由人物 ID、日期、事件类型和基础种子确定。同一输入可重复生成一致结果，不同日期仍会产生变化。
