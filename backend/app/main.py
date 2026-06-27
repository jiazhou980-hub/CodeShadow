from __future__ import annotations

import ast
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="CodeShadow API")
REPOS_DIR = Path("storage/repos")
REPO_INDEX_FILE = REPOS_DIR / ".codeshadow_repos.json"
LESSON_INDEX_FILE = REPOS_DIR / ".codeshadow_lessons.json"
SUPPORTED_CODE_SUFFIXES = {".py", ".js", ".ts", ".tsx"}
IGNORED_DIRS = {"node_modules", ".git", "venv", "__pycache__", "dist", "build"}
LESSON_CHUNK_SIZE = 30

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


class CloneRepoRequest(BaseModel):
    github_url: str


class CloneRepoResponse(BaseModel):
    repo_id: str
    repo_name: str
    local_path: str
    message: str


class FileTreeNode(BaseModel):
    name: str
    path: str
    type: str
    children: list[FileTreeNode] = Field(default_factory=list)


class RepoFilesResponse(BaseModel):
    repo_id: str
    repo_name: str
    tree: list[FileTreeNode]


class LineExplanation(BaseModel):
    line_number: int
    code: str
    explanation: str


class Lesson(BaseModel):
    lesson_id: str
    file_path: str
    start_line: int
    end_line: int
    code: str
    line_explanations: list[LineExplanation]


class GenerateLessonsResponse(BaseModel):
    repo_id: str
    repo_name: str
    lessons: list[Lesson]


class SubmitLessonRequest(BaseModel):
    user_code: str


class SubmitLessonResponse(BaseModel):
    lesson_id: str
    passed: bool
    message: str
    diff_line: int | None = None


def load_repo_index() -> dict[str, dict[str, str]]:
    if not REPO_INDEX_FILE.exists():
        return {}

    try:
        data = json.loads(REPO_INDEX_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}

    return data if isinstance(data, dict) else {}


def load_lesson_index() -> dict[str, dict]:
    if not LESSON_INDEX_FILE.exists():
        return {}

    try:
        data = json.loads(LESSON_INDEX_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}

    return data if isinstance(data, dict) else {}


def save_lesson_index(index: dict[str, dict]) -> None:
    REPOS_DIR.mkdir(parents=True, exist_ok=True)
    LESSON_INDEX_FILE.write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def save_repo_index(index: dict[str, dict[str, str]]) -> None:
    REPOS_DIR.mkdir(parents=True, exist_ok=True)
    REPO_INDEX_FILE.write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def remember_repo(repo_id: str, repo_name: str, local_path: Path) -> None:
    index = load_repo_index()
    index[repo_id] = {
        "repo_name": repo_name,
        "local_path": str(local_path),
    }
    save_repo_index(index)


def get_repo_path(repo_id: str) -> tuple[str, Path]:
    index = load_repo_index()
    repo = index.get(repo_id)

    if repo:
        repo_name = repo["repo_name"]
        repo_path = Path(repo["local_path"])
    else:
        repo_name = repo_id.split("__", 1)[-1]
        repo_path = REPOS_DIR / repo_name

    if not repo_path.exists() or not repo_path.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="未找到该仓库，请先拉取 GitHub 仓库。",
        )

    return repo_name, repo_path


def parse_github_repo_url(github_url: str) -> tuple[str, str, str]:
    parsed = urlparse(github_url.strip())

    if parsed.scheme != "https" or parsed.netloc != "github.com":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请输入 https://github.com/ 开头的公开仓库地址。",
        )

    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) != 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub 仓库地址格式应为 https://github.com/owner/repo。",
        )

    owner, repo_name = parts
    repo_name = repo_name.removesuffix(".git")
    valid_part = re.compile(r"^[A-Za-z0-9_.-]+$")

    if (
        not owner
        or not repo_name
        or not valid_part.match(owner)
        or not valid_part.match(repo_name)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub 仓库地址包含不支持的字符。",
        )

    clone_url = f"https://github.com/{owner}/{repo_name}.git"
    repo_id = f"{owner}__{repo_name}"
    return repo_id, repo_name, clone_url


@app.post("/api/repos/clone", response_model=CloneRepoResponse)
def clone_repo(payload: CloneRepoRequest) -> CloneRepoResponse:
    repo_id, repo_name, clone_url = parse_github_repo_url(payload.github_url)
    local_path = REPOS_DIR / repo_name

    if local_path.exists():
        if not local_path.is_dir():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="目标路径已存在但不是目录，无法拉取仓库。",
            )

        remember_repo(repo_id, repo_name, local_path)
        return CloneRepoResponse(
            repo_id=repo_id,
            repo_name=repo_name,
            local_path=str(local_path),
            message="仓库目录已存在，未重复拉取。",
        )

    REPOS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", clone_url, str(local_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="服务器未安装 git，无法拉取仓库。",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="拉取仓库超时，请稍后重试。",
        ) from exc
    except subprocess.CalledProcessError as exc:
        error_message = exc.stderr.strip() or "拉取仓库失败，请确认这是公开仓库地址。"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_message,
        ) from exc

    remember_repo(repo_id, repo_name, local_path)
    return CloneRepoResponse(
        repo_id=repo_id,
        repo_name=repo_name,
        local_path=str(local_path),
        message="仓库拉取成功。",
    )


def is_inside_ignored_dir(path: Path, repo_path: Path) -> bool:
    relative_parts = path.relative_to(repo_path).parts
    return any(part in IGNORED_DIRS for part in relative_parts)


def find_code_files(repo_path: Path) -> list[Path]:
    code_files: list[Path] = []

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [directory for directory in dirs if directory not in IGNORED_DIRS]
        root_path = Path(root)

        if is_inside_ignored_dir(root_path, repo_path):
            continue

        for file_name in files:
            path = root_path / file_name
            if path.suffix in SUPPORTED_CODE_SUFFIXES:
                code_files.append(path)

    return sorted(code_files, key=lambda item: item.relative_to(repo_path).as_posix())


def build_file_tree(repo_path: Path, code_files: list[Path]) -> list[FileTreeNode]:
    tree: dict[str, dict] = {}

    for file_path in code_files:
        current_level = tree
        relative_parts = file_path.relative_to(repo_path).parts

        for index, part in enumerate(relative_parts):
            is_file = index == len(relative_parts) - 1
            node = current_level.setdefault(
                part,
                {
                    "name": part,
                    "path": "/".join(relative_parts[: index + 1]),
                    "type": "file" if is_file else "directory",
                    "children": {},
                },
            )
            current_level = node["children"]

    def convert(level: dict[str, dict]) -> list[FileTreeNode]:
        nodes: list[FileTreeNode] = []
        for item in sorted(
            level.values(),
            key=lambda node: (node["type"] == "file", node["name"]),
        ):
            nodes.append(
                FileTreeNode(
                    name=item["name"],
                    path=item["path"],
                    type=item["type"],
                    children=convert(item["children"]),
                )
            )
        return nodes

    return convert(tree)


def python_function_ranges(code: str) -> list[tuple[int, int]]:
    try:
        module = ast.parse(code)
    except SyntaxError:
        return []

    ranges: list[tuple[int, int]] = []
    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.end_lineno:
            ranges.append((node.lineno, node.end_lineno))

    return sorted(set(ranges))


def fixed_line_ranges(total_lines: int) -> list[tuple[int, int]]:
    if total_lines == 0:
        return []

    return [
        (start, min(start + LESSON_CHUNK_SIZE - 1, total_lines))
        for start in range(1, total_lines + 1, LESSON_CHUNK_SIZE)
    ]


def lesson_ranges_for_file(path: Path, code: str) -> list[tuple[int, int]]:
    total_lines = len(code.splitlines())

    if path.suffix == ".py":
        ranges = python_function_ranges(code)
        if ranges:
            return ranges

    return fixed_line_ranges(total_lines)


def explain_code_line(code_line: str) -> str:
    stripped = code_line.strip()

    if stripped.startswith(("import ", "from ")):
        return "导入依赖"

    if re.match(r"^(async\s+)?def\s+", stripped) or re.match(
        r"^(export\s+)?(default\s+)?(async\s+)?function\s+",
        stripped,
    ):
        return "定义函数"

    if re.match(r"^(export\s+)?class\s+", stripped):
        return "定义类"

    if stripped.startswith("return"):
        return "返回结果"

    return "业务逻辑代码"


def build_line_explanations(
    lines: list[str],
    start_line: int,
    end_line: int,
) -> list[LineExplanation]:
    return [
        LineExplanation(
            line_number=line_number,
            code=lines[line_number - 1],
            explanation=explain_code_line(lines[line_number - 1]),
        )
        for line_number in range(start_line, end_line + 1)
    ]


def generate_lessons_for_repo(repo_id: str, repo_path: Path) -> list[Lesson]:
    lessons: list[Lesson] = []
    code_files = find_code_files(repo_path)

    for file_path in code_files:
        relative_path = file_path.relative_to(repo_path).as_posix()
        code = file_path.read_text(encoding="utf-8", errors="ignore")
        lines = code.splitlines()

        for start_line, end_line in lesson_ranges_for_file(file_path, code):
            snippet = "\n".join(lines[start_line - 1 : end_line])
            lesson_number = len(lessons) + 1
            lessons.append(
                Lesson(
                    lesson_id=f"{repo_id}-{lesson_number}",
                    file_path=relative_path,
                    start_line=start_line,
                    end_line=end_line,
                    code=snippet,
                    line_explanations=build_line_explanations(
                        lines,
                        start_line,
                        end_line,
                    ),
                )
            )

    return lessons


def remember_lessons(lessons: list[Lesson]) -> None:
    index = load_lesson_index()

    for lesson in lessons:
        index[lesson.lesson_id] = lesson.model_dump()

    save_lesson_index(index)


def hydrate_cached_lesson(lesson: dict) -> Lesson:
    if "line_explanations" in lesson:
        return Lesson.model_validate(lesson)

    code = lesson.get("code", "")
    start_line = int(lesson.get("start_line", 1))
    lines = code.splitlines()
    end_line = start_line + len(lines) - 1

    return Lesson(
        lesson_id=lesson["lesson_id"],
        file_path=lesson["file_path"],
        start_line=start_line,
        end_line=int(lesson.get("end_line", end_line)),
        code=code,
        line_explanations=[
            LineExplanation(
                line_number=start_line + index,
                code=line,
                explanation=explain_code_line(line),
            )
            for index, line in enumerate(lines)
        ],
    )


def normalize_code_for_compare(code: str) -> list[str]:
    return [line.rstrip() for line in code.splitlines()]


def find_first_diff_line(expected_code: str, user_code: str) -> int | None:
    expected_lines = normalize_code_for_compare(expected_code)
    user_lines = normalize_code_for_compare(user_code)
    max_lines = max(len(expected_lines), len(user_lines))

    for index in range(max_lines):
        expected_line = expected_lines[index] if index < len(expected_lines) else None
        user_line = user_lines[index] if index < len(user_lines) else None

        if expected_line != user_line:
            return index + 1

    return None


@app.get("/api/repos/{repo_id}/files", response_model=RepoFilesResponse)
def get_repo_files(repo_id: str) -> RepoFilesResponse:
    repo_name, repo_path = get_repo_path(repo_id)
    code_files = find_code_files(repo_path)

    return RepoFilesResponse(
        repo_id=repo_id,
        repo_name=repo_name,
        tree=build_file_tree(repo_path, code_files),
    )


@app.post("/api/repos/{repo_id}/lessons/generate", response_model=GenerateLessonsResponse)
def generate_lessons(repo_id: str) -> GenerateLessonsResponse:
    repo_name, repo_path = get_repo_path(repo_id)
    lessons = generate_lessons_for_repo(repo_id, repo_path)
    remember_lessons(lessons)

    return GenerateLessonsResponse(
        repo_id=repo_id,
        repo_name=repo_name,
        lessons=lessons,
    )


@app.get("/api/lessons/{lesson_id}", response_model=Lesson)
def get_lesson(lesson_id: str) -> Lesson:
    lesson = load_lesson_index().get(lesson_id)

    if lesson is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="未找到该关卡，请先生成学习关卡。",
        )

    return hydrate_cached_lesson({"lesson_id": lesson_id, **lesson})


@app.post("/api/lessons/{lesson_id}/submit", response_model=SubmitLessonResponse)
def submit_lesson(
    lesson_id: str,
    payload: SubmitLessonRequest,
) -> SubmitLessonResponse:
    lesson = load_lesson_index().get(lesson_id)

    if lesson is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="未找到该关卡，请先生成学习关卡。",
        )

    diff_line = find_first_diff_line(lesson["code"], payload.user_code)

    if diff_line is None:
        return SubmitLessonResponse(
            lesson_id=lesson_id,
            passed=True,
            message="提交正确，关卡已完成。",
        )

    source_line = int(lesson["start_line"]) + diff_line - 1

    return SubmitLessonResponse(
        lesson_id=lesson_id,
        passed=False,
        diff_line=source_line,
        message=f"第 {source_line} 行不一致，请检查该行附近的代码。",
    )
