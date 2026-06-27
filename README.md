# CodeShadow

CodeShadow 是一个面向真实 GitHub 项目的代码跟打学习工具。当前版本包含基础项目骨架、GitHub 仓库拉取、项目文件扫描、基础关卡生成和代码临摹页面：

- `backend/`：FastAPI 服务，提供 `/health` 健康检查接口。
- `backend/`：提供 `POST /api/repos/clone`，接收公开 GitHub 仓库 URL 并 clone 到 `storage/repos/{repo_name}`。
- `backend/`：提供 `GET /api/repos/{repo_id}/files` 和 `POST /api/repos/{repo_id}/lessons/generate`。
- `backend/`：提供 `POST /api/lessons/{lesson_id}/submit`，校验用户临摹代码。
- `frontend/`：React + Vite + TypeScript 首页，提交 GitHub 仓库 URL 后进入代码临摹页面。
- `frontend/`：临摹页面左侧展示关卡列表，中间使用 Monaco Editor，底部展示当前行解释和提交结果。
- `docker-compose.yml`：同时启动前后端开发服务。

## 本地启动

### 使用 Docker Compose

```bash
docker compose up --build
```

启动后访问：

- 前端：http://localhost:5173
- 后端健康检查：http://localhost:8000/health

如果构建时报 Docker Hub 超时，例如 `failed to fetch oauth token` 或 `i/o timeout`，说明本机暂时无法拉取 `python:3.12-slim` / `node:22-alpine` 基础镜像。可以复制环境变量模板并把镜像改成你当前网络可访问的镜像源：

```bash
cp .env.example .env
```

`.env` 示例：

```env
PYTHON_IMAGE=python:3.12-slim
NODE_IMAGE=node:22-alpine
```

改完后重新执行：

```bash
docker compose up --build
```

## API

### 拉取 GitHub 仓库

```http
POST /api/repos/clone
Content-Type: application/json
```

请求体：

```json
{
  "github_url": "https://github.com/owner/repository"
}
```

响应示例：

```json
{
  "repo_id": "owner__repository",
  "repo_name": "repository",
  "local_path": "storage/repos/repository",
  "message": "仓库拉取成功。"
}
```

### 获取核心代码文件树

```http
GET /api/repos/{repo_id}/files
```

当前扫描 `.py`、`.js`、`.ts`、`.tsx` 文件，并忽略 `node_modules`、`.git`、`venv`、`__pycache__`、`dist`、`build`。

### 生成学习关卡

```http
POST /api/repos/{repo_id}/lessons/generate
```

响应中的每个关卡包含：

- `lesson_id`
- `file_path`
- `start_line`
- `end_line`
- `code`
- `line_explanations`

当前行解释规则：

- `import` / `from` 行：导入依赖
- `def` / `function` 行：定义函数
- `class` 行：定义类
- `return` 行：返回结果
- 其他行：业务逻辑代码

### 提交关卡

```http
POST /api/lessons/{lesson_id}/submit
Content-Type: application/json
```

请求体：

```json
{
  "user_code": "用户输入的代码"
}
```

后端会和标准代码逐行比较，忽略行尾空格，但不忽略代码顺序。通过时返回 `passed=true`；不通过时只返回差异行号，不返回完整标准答案。

### 不使用 Docker

后端：

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

前端：

```bash
cd frontend
npm install
npm run dev
```

## 下一步

建议下一步实现 SQLite 持久化和练习提交校验：

1. 新增 SQLite 数据模型，保存仓库、关卡和学习进度。
2. 前端进入练习页，展示单个关卡代码输入区。
3. 后端新增提交接口，对比用户输入和标准代码。
