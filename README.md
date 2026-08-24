# GTA 10,000 人实时位置与行为模拟器

这是一个面向大多伦多地区（GTA）的合成人口移动模拟项目。系统使用 10,000 名成年合成人物、真实 OpenStreetMap 地点、固定人物关系和可调行为规则，在任意时间点实时计算每个人的位置与状态。

当前地点池覆盖 Toronto、North York、Scarborough、Brampton、Markham、Vaughan、Richmond Hill 一带；人物住宅目前只分配在 **Markham** 和 **Scarborough**。

## 核心模型

系统的基本流程是：

```text
当前时间 → 行为日程 → 地点选择 → 道路路线 → 实时位置
```

- 不预先保存 10,000 人每分钟的 GPS 记录。
- API 收到查询后，根据当前时钟、正在进行的事件和路线实时计算位置。
- 默认模拟速度为 `1.0`，即现实 1 秒对应模拟 1 秒；管理员可暂停、跳转或加速。
- 日程以一天为滚动窗口生成，服务跨日后自动补充下一天。
- HOME、WORK 和组织归属是固定绑定；餐厅、咖啡馆、商场等活动地点从真实 OSM POI 中选择。
- 驾车时可以沿本地 OSM 道路图进行 A* 路由；没有道路图时自动退回直线估算。

## 人物、地点与关系

主要数据文件：

- `data/gta_synthetic_population_10000.csv`：原始 10,000 人合成人口。
- `data/gta_population_with_places.csv`：加入 HOME、WORK 和性格字段的运行时人物表。
- `data/places.csv`：约 49 万个真实 OSM 地点，包括住宅、办公、餐饮、零售、医疗、公园等。
- `data/person_places.csv`：人物与 HOME、WORK 等固定地点的绑定。
- `data/organizations.csv`：绑定到真实工作地点的合成公司或组织。
- `data/person_organizations.csv`：人物的组织和团队归属。
- `data/relationships.csv`：样本内家人、伴侣、同事、朋友、邻居等关系；末列 `relationship_context` 结合双方人物属性、性格与相关地点，提供可直接用于 AI 提示词的具体中文关系背景。
- `data/external_contacts.csv`：不属于这 10,000 人的轻量级样本外联系人。
- `data/person_behavior_profiles.csv`：连续性格参数、沟通风格和可直接用于 AI 提示词的中文人物描述。

地点先于关系生成。人物不要求以完整家庭为单位进入样本，因此母亲可能在表内、父亲可能不在表内。默认约 30% 的人物至少拥有一条样本内家庭关系；夫妻共享住宅，成年子女、父母、兄弟姐妹和其他亲属不强制同住。

同事关系来自共同组织或团队；朋友、邻居和室友关系会参考已经分配好的地点与人物属性。约会、朋友外出、拜访朋友和探亲会检查双方空闲时间，并为样本内双方生成同步事件。拜访朋友会使用对方真实 HOME，外出活动会选择真实 POI。

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

`/api/v1/world` 一次返回当前 10,000 人的位置。`compact=true` 使用紧凑数组格式；可通过 `bbox` 只请求地图视野内的人物。

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
- 临时指定某个人在一段时间内的位置和状态

高级 JSON 编辑仍保留，方便备份和批量修改。

## 从 OSM 重新生成数据

仓库已包含 BBBike 导出的 `data/gta-mobility.osm.pbf` 和由其生成的 `data/road_network.pkl`。需要使用更新的 OSM 快照重建全部地点和人物绑定时，可以替换 PBF 后执行：

```bash
python scripts/extract_pbf_places.py
python scripts/build_road_network.py
python scripts/assign_places.py
python scripts/generate_personality_profiles.py
python scripts/validate_personality_profiles.py
python scripts/validate_places.py
python scripts/generate_relationships.py
python scripts/validate_relationships.py
python scripts/generate_external_contacts.py
```

`data/road_network.pkl` 是运行时使用的本地可驾驶道路图，已经随仓库发布。按需生成的路线缓存保存在 `work/routes.sqlite`，不会进入 Git 历史。

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

GitHub 仓库包含 `data/road_network.pkl`，因此 Railway 直接从仓库构建时会加载真实 HOME、WORK、活动 POI 和 GTA 道路路线。首次构建需要额外下载约 124 MiB 的地图与道路数据；运行中生成的路线缓存仍写入 `ROUTE_CACHE_PATH`。

## 环境变量

- `ADMIN_API_KEY`：生产环境必填，至少 16 个字符。
- `ADMIN_USER`：管理界面用户名，默认 `admin`。
- `PUBLIC_API_KEY`：可选；启用后客户端通过 `X-API-Key` 发送。
- `STATE_PATH`：时钟、行为配置和临时交互状态，Railway 默认 `/data/simulator-state.json`。
- `SIMULATION_START`：初始模拟时间。
- `SCHEDULE_DAYS`：滚动日程窗口，默认 `1`。
- `CORS_ORIGINS`：允许访问 API 的来源，逗号分隔。
- `POPULATION_PATH`：默认 `data/gta_population_with_places.csv`。
- `PLACES_PATH`：默认 `data/places.csv`。
- `RELATIONSHIPS_PATH`：默认 `data/relationships.csv`。
- `EXTERNAL_CONTACTS_PATH`：默认 `data/external_contacts.csv`。
- `ROAD_NETWORK_PATH`：默认 `data/road_network.pkl`。
- `ROUTE_CACHE_PATH`：默认 `work/routes.sqlite`。

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
