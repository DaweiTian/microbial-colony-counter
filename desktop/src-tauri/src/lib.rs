use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use tauri::Manager;

const API_PORT: u16 = 18085;
const SIDECAR_IMAGE: &str = "colony-backend.exe";

struct SidecarState {
    child: Mutex<Option<Child>>,
    cleaned: std::sync::atomic::AtomicBool,
}

fn log_dir() -> PathBuf {
    let base = std::env::var("LOCALAPPDATA")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."));
    let d = base.join("colony-counter");
    let _ = std::fs::create_dir_all(&d);
    d
}

fn log_line(msg: &str) {
    let p = log_dir().join("launcher.log");
    if let Ok(mut f) = OpenOptions::new().create(true).append(true).open(p) {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        let _ = writeln!(f, "t={now} {msg}");
    }
    eprintln!("[launcher] {msg}");
}

fn backend_port_open() -> bool {
    use std::net::TcpStream;
    use std::time::Duration;
    TcpStream::connect_timeout(
        &format!("127.0.0.1:{API_PORT}").parse().unwrap(),
        Duration::from_millis(250),
    )
    .is_ok()
}

fn candidate_dirs() -> Vec<PathBuf> {
    let mut dirs = Vec::new();
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            dirs.push(dir.join("sidecar-backend"));
            dirs.push(dir.join("binaries"));
            dirs.push(dir.to_path_buf());
        }
    }
    if let Ok(cwd) = std::env::current_dir() {
        dirs.push(cwd.join("sidecar-backend"));
        dirs.push(cwd.clone());
    }
    dirs
}

fn sidecar_bin_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let names = [SIDECAR_IMAGE];
    let mut dirs = Vec::new();
    if let Ok(res) = app.path().resource_dir() {
        dirs.push(res.join("sidecar-backend"));
        dirs.push(res.clone());
    }
    dirs.extend(candidate_dirs());
    let mut tried = Vec::new();
    for d in dirs {
        for n in names {
            let p = d.join(n);
            tried.push(p.display().to_string());
            if p.is_file() {
                return Ok(p);
            }
        }
    }
    Err(format!("sidecar not found; tried: {tried:?}"))
}

/// 强制结束进程树（含子孙进程），避免覆盖安装时 sidecar 锁文件。
fn force_kill_tree(pid: u32) {
    if pid == 0 {
        return;
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        let _ = Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .creation_flags(CREATE_NO_WINDOW)
            .status();
    }
    #[cfg(not(windows))]
    {
        let _ = Command::new("kill")
            .args(["-9", &pid.to_string()])
            .status();
    }
}

/// 按映像名兜底清残留（安装器关闭主程序后 sidecar 可能仍在）。
fn force_kill_by_image() {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        let _ = Command::new("taskkill")
            .args(["/IM", SIDECAR_IMAGE, "/F"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .creation_flags(CREATE_NO_WINDOW)
            .status();
    }
}

fn spawn_backend(app: &tauri::AppHandle) -> Result<(), String> {
    if backend_port_open() {
        log_line(&format!("port {API_PORT} already open, skip spawn"));
        return Ok(());
    }

    let bin = sidecar_bin_path(app)?;
    log_line(&format!("spawning {}", bin.display()));
    let workdir = bin
        .parent()
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_default());

    let parent_pid = std::process::id();
    let mut cmd = Command::new(&bin);
    cmd.current_dir(&workdir)
        .env("COLONY_HOST", "127.0.0.1")
        .env("COLONY_PORT", API_PORT.to_string())
        .env("COLONY_NO_BROWSER", "1")
        .env("COLONY_PARENT_PID", parent_pid.to_string())
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    let child = cmd.spawn().map_err(|e| {
        let m = format!("spawn failed: {e} bin={}", bin.display());
        log_line(&m);
        m
    })?;

    log_line(&format!("spawned pid={} parent={parent_pid}", child.id()));
    if let Some(state) = app.try_state::<SidecarState>() {
        *state.child.lock().unwrap() = Some(child);
    }

    for i in 0..45 {
        if backend_port_open() {
            log_line(&format!("backend ready after {}s", i + 1));
            return Ok(());
        }
        std::thread::sleep(std::time::Duration::from_secs(1));
    }
    log_line("backend not ready after 45s");
    Err("backend not ready in 45s".into())
}

fn kill_sidecar(app: &tauri::AppHandle) {
    // Destroyed + Exit 可能各触发一次，避免重复 taskkill 弹黑框
    if let Some(state) = app.try_state::<SidecarState>() {
        if state
            .cleaned
            .swap(true, std::sync::atomic::Ordering::SeqCst)
        {
            return;
        }
        let mut pid_opt = None;
        if let Ok(mut guard) = state.child.lock() {
            if let Some(mut child) = guard.take() {
                pid_opt = Some(child.id());
                let _ = child.kill();
                let _ = child.wait();
            }
        }
        if let Some(pid) = pid_opt {
            log_line(&format!("force kill tree pid={pid}"));
            force_kill_tree(pid);
        }
        force_kill_by_image();
        log_line("sidecar cleanup done");
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(SidecarState {
            child: Mutex::new(None),
            cleaned: std::sync::atomic::AtomicBool::new(false),
        })
        .setup(|app| {
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                if let Err(e) = spawn_backend(&handle) {
                    log_line(&format!("backend start error: {e}"));
                }
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                kill_sidecar(window.app_handle());
            }
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(|app_handle, event| {
            if let tauri::RunEvent::Exit = event {
                kill_sidecar(app_handle);
            }
        });
}
