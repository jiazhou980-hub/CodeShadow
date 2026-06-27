import Editor, { type OnMount } from "@monaco-editor/react";
import { useEffect, useMemo, useState, type FormEvent } from "react";

type CloneResult = {
  repo_id: string;
  repo_name: string;
  local_path: string;
  message: string;
};

type LineExplanation = {
  line_number: number;
  code: string;
  explanation: string;
};

type Lesson = {
  lesson_id: string;
  file_path: string;
  start_line: number;
  end_line: number;
  code: string;
  line_explanations: LineExplanation[];
};

type SubmitResult = {
  lesson_id: string;
  passed: boolean;
  message: string;
  diff_line?: number | null;
};

const API_BASE_URL = "http://localhost:8000";

function getEditorLanguage(filePath: string) {
  if (filePath.endsWith(".py")) {
    return "python";
  }

  if (filePath.endsWith(".tsx")) {
    return "typescript";
  }

  if (filePath.endsWith(".ts")) {
    return "typescript";
  }

  if (filePath.endsWith(".js")) {
    return "javascript";
  }

  return "plaintext";
}

function App() {
  const [repoUrl, setRepoUrl] = useState("");
  const [result, setResult] = useState<CloneResult | null>(null);
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [selectedLessonId, setSelectedLessonId] = useState("");
  const [lessonDetailsById, setLessonDetailsById] = useState<Record<string, Lesson>>(
    {},
  );
  const [cursorLine, setCursorLine] = useState(1);
  const [userCodeByLesson, setUserCodeByLesson] = useState<Record<string, string>>(
    {},
  );
  const [completedLessonIds, setCompletedLessonIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [submitResult, setSubmitResult] = useState<SubmitResult | null>(null);
  const [lessonError, setLessonError] = useState("");
  const [isLessonLoading, setIsLessonLoading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const selectedLesson = useMemo(
    () =>
      lessonDetailsById[selectedLessonId] ??
      lessons.find((lesson) => lesson.lesson_id === selectedLessonId) ??
      null,
    [lessonDetailsById, lessons, selectedLessonId],
  );

  const editorValue = selectedLesson
    ? userCodeByLesson[selectedLesson.lesson_id] ?? selectedLesson.code
    : "";

  const currentExplanation =
    selectedLesson?.line_explanations[cursorLine - 1]?.explanation ??
    "业务逻辑代码";

  useEffect(() => {
    setCursorLine(1);
    setSubmitResult(null);
  }, [selectedLessonId]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setResult(null);
    setLessons([]);
    setSelectedLessonId("");
    setLessonDetailsById({});
    setUserCodeByLesson({});
    setCompletedLessonIds(new Set());
    setSubmitResult(null);
    setIsLoading(true);

    try {
      const response = await fetch(`${API_BASE_URL}/api/repos/clone`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ github_url: repoUrl }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "拉取仓库失败，请稍后重试。");
      }

      setResult(data);

      const lessonsResponse = await fetch(
        `${API_BASE_URL}/api/repos/${data.repo_id}/lessons/generate`,
        {
          method: "POST",
        },
      );
      const lessonsData = await lessonsResponse.json();

      if (!lessonsResponse.ok) {
        throw new Error(lessonsData.detail || "生成关卡失败，请稍后重试。");
      }

      setLessons(lessonsData.lessons);
      setLessonDetailsById(
        Object.fromEntries(
          lessonsData.lessons.map((lesson: Lesson) => [lesson.lesson_id, lesson]),
        ),
      );

      if (lessonsData.lessons[0]) {
        await selectLesson(lessonsData.lessons[0].lesson_id);
      }
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "网络异常，请确认后端服务已启动。",
      );
    } finally {
      setIsLoading(false);
    }
  }

  const handleEditorMount: OnMount = (editor) => {
    setCursorLine(editor.getPosition()?.lineNumber ?? 1);
    editor.onDidChangeCursorPosition((event) => {
      setCursorLine(event.position.lineNumber);
    });
  };

  async function selectLesson(lessonId: string) {
    setSelectedLessonId(lessonId);
    setLessonError("");
    setIsLessonLoading(true);

    try {
      const response = await fetch(`${API_BASE_URL}/api/lessons/${lessonId}`);
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "加载关卡详情失败，请稍后重试。");
      }

      setLessonDetailsById((current) => ({
        ...current,
        [lessonId]: data,
      }));
    } catch (caughtError) {
      setLessonError(
        caughtError instanceof Error
          ? caughtError.message
          : "网络异常，请确认后端服务已启动。",
      );
    } finally {
      setIsLessonLoading(false);
    }
  }

  function updateUserCode(value: string | undefined) {
    if (!selectedLesson) {
      return;
    }

    setUserCodeByLesson((current) => ({
      ...current,
      [selectedLesson.lesson_id]: value ?? "",
    }));
  }

  async function submitCurrentLesson() {
    if (!selectedLesson) {
      return;
    }

    setSubmitResult(null);
    setIsSubmitting(true);

    try {
      const response = await fetch(
        `${API_BASE_URL}/api/lessons/${selectedLesson.lesson_id}/submit`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            user_code:
              userCodeByLesson[selectedLesson.lesson_id] ?? selectedLesson.code,
          }),
        },
      );
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "提交失败，请稍后重试。");
      }

      setSubmitResult(data);

      if (data.passed) {
        setCompletedLessonIds((current) => {
          const next = new Set(current);
          next.add(selectedLesson.lesson_id);
          return next;
        });
      }
    } catch (caughtError) {
      setSubmitResult({
        lesson_id: selectedLesson.lesson_id,
        passed: false,
        message:
          caughtError instanceof Error
            ? caughtError.message
            : "网络异常，请确认后端服务已启动。",
      });
    } finally {
      setIsSubmitting(false);
    }
  }

  if (selectedLesson) {
    return (
      <main className="lesson-page">
        <aside className="lesson-sidebar">
          <div className="sidebar-header">
            <button type="button" onClick={() => setSelectedLessonId("")}>
              返回首页
            </button>
            <div>
              <p className="eyebrow">CodeShadow</p>
              <h1>{result?.repo_name ?? "Lessons"}</h1>
            </div>
          </div>

          <ol className="sidebar-list">
            {lessons.map((lesson, index) => (
              <li key={lesson.lesson_id}>
                <button
                  className={[
                    lesson.lesson_id === selectedLesson.lesson_id ? "active" : "",
                    completedLessonIds.has(lesson.lesson_id) ? "completed" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  type="button"
                  onClick={() => selectLesson(lesson.lesson_id)}
                >
                  <span>
                    关卡 {index + 1}
                    {completedLessonIds.has(lesson.lesson_id) ? " · 已完成" : ""}
                  </span>
                  <strong>{lesson.file_path}</strong>
                  <small>
                    第 {lesson.start_line} - {lesson.end_line} 行
                  </small>
                </button>
              </li>
            ))}
          </ol>
        </aside>

        <section className="practice-workspace">
          <header className="lesson-topbar">
            <div>
              <span>当前文件</span>
              <h2>{selectedLesson.file_path}</h2>
            </div>
            <p>
              第 {selectedLesson.start_line} - {selectedLesson.end_line} 行
            </p>
          </header>

          <div className="editor-shell">
            <Editor
              key={selectedLesson.lesson_id}
              height="100%"
              language={getEditorLanguage(selectedLesson.file_path)}
              onChange={updateUserCode}
              onMount={handleEditorMount}
              options={{
                fontSize: 15,
                lineNumbers: "on",
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                wordWrap: "on",
              }}
              theme="vs-dark"
              value={editorValue}
            />
          </div>

          {isLessonLoading && (
            <p className="status-message muted">正在加载关卡详情...</p>
          )}

          {lessonError && <p className="status-message error">{lessonError}</p>}

          <div className="submit-bar">
            <button
              type="button"
              onClick={submitCurrentLesson}
              disabled={isSubmitting}
            >
              {isSubmitting ? "提交中..." : "提交"}
            </button>
            {submitResult && (
              <p
                className={
                  submitResult.passed
                    ? "submit-message passed"
                    : "submit-message failed"
                }
              >
                {submitResult.message}
              </p>
            )}
          </div>

          <footer className="explanation-panel">
            <div>
              <span>当前行解释</span>
              <strong>
                第 {selectedLesson.start_line + cursorLine - 1} 行
              </strong>
            </div>
            <p>{currentExplanation}</p>
          </footer>
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <section className="hero">
        <div>
          <p className="eyebrow">Learn real repositories by typing them</p>
          <h1>CodeShadow</h1>
          <p className="intro">
            输入一个公开 GitHub 仓库地址，系统会生成循序渐进的代码临摹关卡。
          </p>
        </div>

        <form className="repo-form" onSubmit={handleSubmit}>
          <label htmlFor="repo-url">GitHub 仓库 URL</label>
          <div className="input-row">
            <input
              id="repo-url"
              name="repo-url"
              type="url"
              placeholder="https://github.com/owner/repository"
              value={repoUrl}
              onChange={(event) => setRepoUrl(event.target.value)}
              required
            />
            <button type="submit" disabled={isLoading}>
              {isLoading ? "分析中..." : "开始分析"}
            </button>
          </div>

          {error && <p className="status-message error">{error}</p>}

          {result && !isLoading && lessons.length === 0 && !error && (
            <p className="status-message muted">
              未发现可生成关卡的核心代码文件。
            </p>
          )}
        </form>
      </section>
    </main>
  );
}

export default App;
