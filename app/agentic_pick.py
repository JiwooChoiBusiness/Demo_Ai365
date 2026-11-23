"""Agentic 모드 폴더 선택 창(2026-10-19): 서버 PC 에 운영체제 폴더 선택 창을 띄우는 자식 프로세스.

`python -m app.agentic_pick <start> <title>` 로 돈다(agentic_api 의 POST /api/agentic/pick-folder 가 pythonw.exe 로 부른다).
tkinter 로 숨긴 루트 창(맨 위 고정)을 만들고 filedialog.askdirectory(mustexist) 를 띄운 뒤, 결과를 JSON 한 줄
{"path": <realpath 또는 "">} 로 stdout 에 찍는다(취소 = 빈 path). JSON 은 ASCII 로만 찍어 자식의 콘솔 인코딩과 무관하다.
루트가 맨 위 고정이라 그 루트가 주인인 폴더 창도 맨 위에 뜬다(다른 프로그램이 포커스를 쥐고 있어도 가려지지 않는다).
Tk 를 띄울 수 없으면(tkinter 가 없거나 화면이 없음) 종료 코드 3, 그 밖의 예기치 못한 오류는 1 이다(부모는 둘 다 503).
테스트 이음새: 환경 변수 AI365_PICK_FAKE 가 있으면 창 없이 그 값을 path 로 찍는다(빈 문자열 = 취소).
실 창 확인용: AI365_PICK_AUTOCLOSE_MS 가 있으면 root.after(ms, root.destroy) 로 창을 스스로 닫는다. 주인(루트)이 부서지면
네이티브 폴더 창도 함께 닫히고 askdirectory 는 취소("")로 돌아온다(2026-10-19 Windows 11 실측: 타이머 때 맨 위 고정 #32770
창이 떠 있었고 부순 뒤 1초 안에 창이 사라지며 "" 로 돌아왔다). 부서진 루트 때문에 TclError 가 나면 그것도 취소로 본다.
"""
# Agentic mode folder picker (2026-10-19): a child process that shows the operating system's folder dialog on the server PC.
# Runs as `python -m app.agentic_pick <start> <title>` (POST /api/agentic/pick-folder in agentic_api starts it with
# pythonw.exe). tkinter builds a hidden, topmost root window and shows filedialog.askdirectory (mustexist), then the result
# goes to stdout as one JSON line {"path": <realpath or "">} (cancel = empty path). The JSON is ASCII only, so the child's
# console encoding never matters. The root is topmost, so the folder window it owns opens on top as well, even while
# another program holds the focus. Exit code 3 when Tk cannot start (no tkinter or no display), 1 for any other unexpected
# error (the parent answers 503 for both).
# Test seam: when AI365_PICK_FAKE is set, no window opens and its value is printed as the path (empty string = cancel).
# Real-window check: AI365_PICK_AUTOCLOSE_MS closes the window by itself through root.after(ms, root.destroy). Destroying
# the owner (the root) closes the native folder window with it and askdirectory comes back cancelled ("") (measured on
# Windows 11, 2026-10-19: a topmost #32770 dialog was up when the timer fired, and within a second of the destroy it was gone
# and "" came back). A TclError caused by the destroyed root counts as a cancel too.

import json
import os
import sys

FAKE_ENV = "AI365_PICK_FAKE"
AUTOCLOSE_ENV = "AI365_PICK_AUTOCLOSE_MS"
EXIT_NO_TK = 3          # Tk 를 띄울 수 없다 / Tk is unavailable
TITLE_MAX = 200


class NoTk(RuntimeError):
    """tkinter 가 없거나 Tk 를 띄울 수 없다(화면이 없는 서버 등) / no tkinter, or Tk cannot start (a server without a display)"""


def _emit(obj: dict) -> None:
    """JSON 한 줄을 stdout 에(ASCII). pythonw 로 돌고 stdout 이 없으면 조용히 넘어간다
    One ASCII JSON line to stdout; quietly skipped when pythonw runs without a stdout"""
    out = sys.stdout
    if out is None:
        return
    out.write(json.dumps(obj) + "\n")
    out.flush()


def _say(msg: str) -> None:
    """stderr 에 한 줄(부모가 로그에 남긴다) / one line to stderr for the parent's log"""
    err = sys.stderr
    if err is not None:
        err.write(msg + "\n")
        err.flush()


def _autoclose_ms() -> int:
    try:
        ms = int(str(os.environ.get(AUTOCLOSE_ENV) or "").strip() or 0)
    except ValueError:
        return 0
    return ms if ms > 0 else 0


def _dpi_aware() -> None:
    """고해상도 화면에서 창이 흐리지 않게(창을 만들기 전에만 뜻이 있다) / crisp on high-DPI screens (only before any window)"""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001 (옛 Windows 이거나 이미 정해졌으면 그대로 / older Windows or already set)
        pass


def choose(start: str = "", title: str = "") -> str:
    """폴더 선택 창 → 고른 폴더의 realpath(취소 = ""). Tk 를 띄울 수 없으면 NoTk
    Show the folder dialog → the realpath of the chosen folder ("" = cancelled); NoTk when Tk cannot start"""
    fake = os.environ.get(FAKE_ENV)
    if fake is not None:
        return fake
    try:
        import tkinter
        from tkinter import filedialog
    except ImportError as e:
        raise NoTk(f"tkinter 를 불러오지 못했습니다: {e}") from e
    _dpi_aware()
    try:
        root = tkinter.Tk()
    except tkinter.TclError as e:
        raise NoTk(f"Tk 를 띄우지 못했습니다: {e}") from e
    state = {"timer": False}

    def autoclose():
        state["timer"] = True
        root.destroy()   # 주인이 부서지면 네이티브 창도 닫히고 취소로 돌아온다 / the owner goes, the native window closes as cancelled

    path = ""
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        root.update()
        ms = _autoclose_ms()
        if ms:
            root.after(ms, autoclose)
        try:
            path = filedialog.askdirectory(parent=root, initialdir=start or None, title=(title or None), mustexist=True)
        except tkinter.TclError:
            if not state["timer"]:   # 타이머가 부순 경우만 취소로 본다 / only a timer-made close counts as cancel
                raise
            path = ""
    finally:
        try:
            root.destroy()
        except tkinter.TclError:   # 타이머가 이미 부쉈다 / the timer already destroyed it
            pass
    path = str(path or "")
    return os.path.realpath(path) if path else ""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    start = args[0] if args else ""
    title = " ".join((args[1] if len(args) > 1 else "").split())[:TITLE_MAX]
    try:
        path = choose(start, title)
    except NoTk as e:
        _say(str(e))
        return EXIT_NO_TK
    _emit({"path": path})
    return 0


if __name__ == "__main__":
    sys.exit(main())
