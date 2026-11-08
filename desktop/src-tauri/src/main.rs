#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::Write;
use std::net::TcpStream;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use log::{error, info, warn};
use tauri::{Emitter, Manager, RunEvent};

/// Owns the backend sidecar child so shutdown kills the exact process we spawned
/// (PID-correct) instead of matching by name with `pkill -f lifelogr-backend`,
/// which could hit an unrelated process sharing that token.
struct SidecarChild(Mutex<Option<tauri_plugin_shell::process::CommandChild>>);

/// Set by the "Close anyway" button while the shutdown guard is waiting for an
/// in-flight backup. The wait loop polls it (300 ms) and gives up.
struct ExitState(AtomicBool);

/// Called from the shutdown overlay. Merely stops waiting — teardown and exit
/// still go through the same path, so the sidecar is never orphaned.
#[tauri::command]
fn exit_now(force: bool, state: tauri::State<ExitState>) {
    if force {
        info!("Shutdown guard: user asked to stop waiting");
        state.0.store(true, Ordering::SeqCst);
    }
}
use tauri::ipc::Response;
use tauri_plugin_global_shortcut::{Builder as ShortcutBuilder, GlobalShortcutExt, ShortcutState};
use tauri_plugin_shell::ShellExt;

/// Read backend port from DIARI_PORT env var, defaulting to 18765.
///
/// 18765 is baked into the frontend API client (`client.ts`) and the Tauri
/// CSP (`tauri.conf.json`), so DIARI_PORT is a dev/test override only —
/// anything other than the default silently breaks the webview's fetches.
fn backend_port() -> u16 {
    std::env::var("DIARI_PORT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(18765)
}

/// Check which system dependencies are installed.
#[tauri::command]
fn check_deps() -> serde_json::Value {
    let ollama = std::process::Command::new("ollama")
        .arg("list")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false);

    // Check if gstreamer1.0-plugins-bad is installed (needed for audio recording)
    let gst_plugins_bad = std::process::Command::new("gst-inspect-1.0")
        .arg("webrtcbin")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false);

    // Tesseract is required for note-image OCR (declared in deb `depends`).
    let tesseract = std::process::Command::new("tesseract")
        .arg("--version")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false);

    serde_json::json!({
        "ollama": ollama,
        "gst_plugins_bad": gst_plugins_bad,
        "tesseract": tesseract,
        "all_installed": ollama && gst_plugins_bad && tesseract,
    })
}

/// Run the first-run setup script (Linux only). Requires pkexec for sudo.
#[tauri::command]
async fn run_setup(app: tauri::AppHandle) -> Result<String, String> {
    #[cfg(target_os = "linux")]
    {
        let resource = app
            .path()
            .resource_dir()
            .map_err(|e| format!("Resource dir error: {e}"))?
            .join("scripts/setup-linux.sh");

        if !resource.exists() {
            return Err(format!("Setup script not found: {}", resource.display()));
        }

        let output = std::process::Command::new("pkexec")
            .arg(&resource)
            .output()
            .map_err(|e| format!("Failed to run setup: {e}"))?;

        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        let stderr = String::from_utf8_lossy(&output.stderr).to_string();

        if output.status.success() {
            Ok(stdout)
        } else {
            Err(format!("{stdout}\n{stderr}"))
        }
    }

    #[cfg(not(target_os = "linux"))]
    {
        let _ = app;
        Err("System setup is only available on Linux.".to_string())
    }
}

/// Probe the backend sidecar via TCP until it accepts connections or timeout.
fn wait_for_sidecar(port: u16) {
    let addr = format!("127.0.0.1:{port}");
    for _ in 0..60 {
        if TcpStream::connect_timeout(&addr.parse().unwrap(), Duration::from_millis(500)).is_ok() {
            info!("Backend sidecar is ready on port {port}");
            return;
        }
        std::thread::sleep(Duration::from_millis(500));
    }
    warn!("Backend sidecar did not become ready within 30s on port {port}");
}

/// Whether anything is currently listening on 127.0.0.1:port.
fn port_is_listening(port: u16) -> bool {
    let addr = format!("127.0.0.1:{port}");
    TcpStream::connect_timeout(&addr.parse().unwrap(), Duration::from_millis(300)).is_ok()
}

/// Reclaim the sidecar port if a stale backend holds it.
///
/// A previous LifeLogr that crashed or was force-killed can leave its backend
/// sidecar running on our port. The new sidecar then fails to bind and exits —
/// but `wait_for_sidecar` only TCP-probes the port, so it sees the *stale*
/// process as healthy and the app silently talks to an outdated backend (the
/// cause of "405 Method Not Allowed" on new endpoints). Single-instance is
/// enforced, so anything on our port at startup is stale — kill it before
/// spawning ours. Best-effort and no-op when the port is already free.
/// True if whatever answers on `port` speaks LifeLogr's /health contract.
///
/// `reclaim_port` kills the process holding our port, so it must never fire on
/// a *foreign* listener (a user's unrelated service that happens to squat
/// 18765). Only a stale own sidecar answers /health with 200 + "ok".
fn port_is_lifelogr(port: u16) -> bool {
    let addr = format!("127.0.0.1:{port}");
    let Ok(mut stream) =
        TcpStream::connect_timeout(&addr.parse().unwrap(), Duration::from_millis(300))
    else {
        return false;
    };
    let req =
        format!("GET /health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n");
    if stream.write_all(req.as_bytes()).is_err() {
        return false;
    }
    let mut buf = [0u8; 512];
    use std::io::Read;
    let n = stream.read(&mut buf).unwrap_or(0);
    let resp = String::from_utf8_lossy(&buf[..n]);
    resp.contains("200") && resp.contains("ok")
}

fn reclaim_port(port: u16) {
    if !port_is_listening(port) {
        return; // port free — nothing to reclaim
    }
    if !port_is_lifelogr(port) {
        error!(
            "Port {port} is held by a process that does not answer LifeLogr's \
             /health — NOT killing it. Free the port manually or set DIARI_PORT."
        );
        return;
    }
    warn!("Port {port} is already in use — reclaiming it from a stale backend sidecar");
    // fuser kills exactly the process holding the port (psmisc, standard on
    // Debian/Ubuntu); fall back to matching the sidecar name if fuser is absent.
    let port_arg = format!("{port}/tcp");
    let reclaimed = std::process::Command::new("fuser")
        .arg("-k")
        .arg(&port_arg)
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
        || std::process::Command::new("pkill")
            .args(["-f", "lifelogr-backend"])
            .status()
            .map(|s| s.success())
            .unwrap_or(false);
    if !reclaimed {
        warn!("Could not reclaim port {port} (no fuser/pkill) — sidecar may fail to bind");
    }
    // Wait for the port to actually free up before we spawn our sidecar.
    for _ in 0..20 {
        if !port_is_listening(port) {
            info!("Port {port} reclaimed");
            return;
        }
        std::thread::sleep(Duration::from_millis(150));
    }
    warn!("Port {port} still in use after reclaim attempt");
}

/// Max time to wait for the backend to close its socket after SIGTERM.
/// The backend's own teardown is bounded to 2 s, so this leaves headroom.
const SIDECAR_GRACE: Duration = Duration::from_millis(2_500);

/// How long the close guard will wait for an in-flight backup before giving up.
const BACKUP_WAIT_LIMIT: Duration = Duration::from_secs(120);

/// `signal(pid, SIGTERM/SIGKILL)` without pulling in a process-name match.
const SIGTERM: i32 = 15;
const SIGKILL: i32 = 9;

#[cfg(unix)]
fn signal(pid: u32, sig: i32) {
    unsafe {
        libc::kill(pid as i32, sig);
    }
}

#[cfg(not(unix))]
fn signal(_pid: u32, _sig: i32) {}

/// Minimal HTTP GET against the local backend. Returns the response body.
fn http_get(port: u16, path: &str) -> Option<String> {
    use std::io::Read;
    let addr: std::net::SocketAddr = format!("127.0.0.1:{port}").parse().ok()?;
    let mut stream = TcpStream::connect_timeout(&addr, Duration::from_millis(500)).ok()?;
    stream
        .set_read_timeout(Some(Duration::from_millis(1_500)))
        .ok()?;
    stream
        .set_write_timeout(Some(Duration::from_millis(1_500)))
        .ok()?;
    let request =
        format!("GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n");
    stream.write_all(request.as_bytes()).ok()?;
    let mut raw = String::new();
    stream.read_to_string(&mut raw).ok()?;
    raw.split("\r\n\r\n").nth(1).map(str::to_string)
}

/// Whether the backend reports un-interruptible work (backup/import/restore).
/// Unreachable backend => not busy: there is nothing left to protect.
fn backend_busy_state(port: u16) -> Option<serde_json::Value> {
    let body = http_get(port, "/api/v1/system/shutdown-state")?;
    serde_json::from_str(&body).ok()
}

/// Stop the sidecar precisely and boundedly.
///
/// In a PyInstaller one-file build the bootloader and the Python process are
/// different PIDs, and only the Python one runs FastAPI's lifespan teardown.
/// The process that owns the listening socket is that process, so SIGTERM goes
/// there first (PID-correct — never a name match); the spawned child handle is
/// a fallback for builds where `lsof` is missing.
fn stop_backend(app: &tauri::AppHandle, port: u16) {
    let mut child = app
        .try_state::<SidecarChild>()
        .and_then(|state| state.0.lock().ok()?.take());

    let owner = port_owner_pid(port);
    if let Some(pid) = owner {
        info!("Stopping backend (pid {pid}) with SIGTERM");
        signal(pid, SIGTERM);
    }
    if let Some(c) = child.as_mut() {
        signal(c.pid(), SIGTERM);
    }

    let deadline = Instant::now() + SIDECAR_GRACE;
    while Instant::now() < deadline {
        if !port_is_listening(port) {
            info!("Backend stopped gracefully");
            break;
        }
        std::thread::sleep(Duration::from_millis(100));
    }

    if port_is_listening(port) {
        warn!(
            "Backend did not exit within {:?} — sending SIGKILL",
            SIDECAR_GRACE
        );
        if let Some(pid) = port_owner_pid(port).or(owner) {
            signal(pid, SIGKILL);
        }
        if let Some(c) = child.take() {
            let _ = c.kill();
        }
    }

    // The handle is consumed by kill(); dropping the Option otherwise is
    // enough — we exit immediately afterwards.
    drop(child);
}

#[cfg(not(target_os = "linux"))]
fn port_owner_pid(_port: u16) -> Option<u32> {
    None
}

/// Close sequence: wait for protected work, hide the window, stop the backend,
/// exit. Runs on its own thread so the UI never blocks on teardown.
fn begin_shutdown(app: tauri::AppHandle) {
    let port = backend_port();
    let mut state = backend_busy_state(port).unwrap_or_default();

    if state
        .get("busy")
        .and_then(serde_json::Value::as_bool)
        .unwrap_or(false)
    {
        info!("Close guard: protected work in flight — waiting");
        let _ = app.emit("shutdown-pending", &state);
        let deadline = Instant::now() + BACKUP_WAIT_LIMIT;
        loop {
            let forced = app.state::<ExitState>().0.load(Ordering::SeqCst);
            if forced {
                info!("Close guard: wait cancelled by the user");
                break;
            }
            if Instant::now() >= deadline {
                warn!("Close guard: wait limit reached — closing anyway");
                break;
            }
            state = backend_busy_state(port).unwrap_or_default();
            if !state
                .get("busy")
                .and_then(serde_json::Value::as_bool)
                .unwrap_or(false)
            {
                info!("Close guard: protected work finished");
                break;
            }
            std::thread::sleep(Duration::from_millis(300));
        }
    }

    if let Some(window) = app.get_webview_window("main") {
        let _ = window.hide();
    }
    stop_backend(&app, port);
    std::process::exit(0);
}

/// Best-effort PID owning a TCP port, via `lsof`. `None` if lsof is unavailable
/// or the port has no identifiable owner.
#[cfg(target_os = "linux")]
fn port_owner_pid(port: u16) -> Option<u32> {
    let out = std::process::Command::new("lsof")
        .args(["-ti", &format!(":{port}")])
        .output()
        .ok()?;
    String::from_utf8_lossy(&out.stdout)
        .lines()
        .filter_map(|line| line.trim().parse::<u32>().ok())
        .next()
}

/// Confirm our sidecar actually owns the port it reports ready on. Catches the
/// TOCTOU window where a foreign process grabs the port between `reclaim_port`
/// and our sidecar's bind — otherwise we'd TCP-probe that foreign listener and
/// silently talk to a stale backend. Best-effort, Linux only; silent when lsof
/// is absent.
#[cfg(target_os = "linux")]
fn verify_sidecar_owner(port: u16, expected_pid: u32) {
    match port_owner_pid(port) {
        Some(pid) if pid == expected_pid => info!("Verified sidecar pid {pid} owns port {port}"),
        Some(other) => warn!(
            "Port {port} is owned by pid {other}, not our sidecar (pid {expected_pid}) — \
             the app may be talking to a stale backend; try restarting LifeLogr."
        ),
        None => {}
    }
}

/// No-op on non-Linux targets (lsof-based verification isn't available).
#[cfg(not(target_os = "linux"))]
fn verify_sidecar_owner(_port: u16, _expected_pid: u32) {}

fn init_logging(data_dir: &std::path::Path) {
    let log_path = data_dir.join("lifelogr-desktop.log");
    let log_file = std::fs::File::create(&log_path).expect("failed to create log file");
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info"))
        .target(env_logger::Target::Pipe(Box::new(log_file)))
        .format(|buf, record| {
            writeln!(
                buf,
                "[{} {}] {}",
                record.level(),
                record.target(),
                record.args()
            )
        })
        .init();
    info!("Logging initialised — writing to {}", log_path.display());
}

/// True when the current session is Wayland (where GNOME has no screencopy
/// protocol and xcap cannot capture).
#[cfg(all(feature = "snip-wayland", target_os = "linux"))]
fn is_wayland_session() -> bool {
    match std::env::var("XDG_SESSION_TYPE") {
        Ok(value) => value.eq_ignore_ascii_case("wayland"),
        Err(_) => std::env::var_os("WAYLAND_DISPLAY").is_some(),
    }
}

/// Capture through `org.freedesktop.portal.Screenshot` (version 2 on GNOME).
///
/// Non-interactive returns the whole screen, which feeds the existing crop
/// overlay unchanged. Interactive is the fallback when the portal requires a
/// grant: GNOME shows its own region UI, and the returned image is already
/// cropped (the app's overlay then crops within it — mildly redundant but
/// harmless, and better than failing).
#[cfg(all(feature = "snip-wayland", target_os = "linux"))]
fn portal_screenshot(interactive: bool) -> Result<Vec<u8>, String> {
    use ashpd::desktop::screenshot::Screenshot;

    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|e| format!("portal runtime: {e}"))?;
    runtime.block_on(async move {
        let response = Screenshot::request()
            .interactive(interactive)
            .modal(true)
            .send()
            .await
            .map_err(|e| format!("portal request failed: {e}"))?
            .response()
            .map_err(|e| format!("portal capture failed: {e}"))?;
        let parsed = url::Url::parse(response.uri().as_str())
            .map_err(|e| format!("portal returned an invalid URI: {e}"))?;
        let path = parsed
            .to_file_path()
            .map_err(|_| "portal returned a non-file URI".to_string())?;
        std::fs::read(&path).map_err(|e| format!("read portal screenshot: {e}"))
    })
}

/// Last-resort fallback for systems where the portal is missing but the GNOME
/// helper is installed. Writes to a private temp file and removes it again.
#[cfg(all(feature = "snip-wayland", target_os = "linux"))]
fn gnome_screenshot_png() -> Result<Vec<u8>, String> {
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0);
    let path =
        std::env::temp_dir().join(format!("lifelogr-snip-{}-{stamp}.png", std::process::id()));
    let status = std::process::Command::new("gnome-screenshot")
        .args(["-f", &path.to_string_lossy()])
        .status()
        .map_err(|e| format!("gnome-screenshot not available: {e}"))?;
    if !status.success() {
        return Err("gnome-screenshot exited with an error".to_string());
    }
    let bytes = std::fs::read(&path).map_err(|e| format!("read screenshot: {e}"))?;
    let _ = std::fs::remove_file(&path);
    Ok(bytes)
}

/// Capture the screen as a PNG byte buffer.
///
/// On Wayland this goes through the desktop portal; elsewhere it grabs the
/// first available monitor with xcap. The first monitor is used rather than
/// detecting "primary" so the call works across xcap versions whose
/// monitor-selection API differs — for the typical single-monitor setup it is
/// the whole screen.
#[cfg(feature = "snip")]
fn capture_primary_monitor_png() -> Result<Vec<u8>, String> {
    // On Wayland the portal is the only supported route: xcap needs
    // zwlr_screencopy_manager_v1, which GNOME deliberately does not implement.
    #[cfg(all(feature = "snip-wayland", target_os = "linux"))]
    if is_wayland_session() {
        let mut failures: Vec<String> = Vec::new();
        match portal_screenshot(false) {
            Ok(png) => return Ok(png),
            Err(e) => failures.push(format!("portal: {e}")),
        }
        match portal_screenshot(true) {
            Ok(png) => return Ok(png),
            Err(e) => failures.push(format!("portal (interactive): {e}")),
        }
        if std::process::Command::new("gnome-screenshot")
            .arg("--version")
            .output()
            .is_ok()
        {
            match gnome_screenshot_png() {
                Ok(png) => return Ok(png),
                Err(e) => failures.push(format!("gnome-screenshot: {e}")),
            }
        }
        return Err(format!(
            "Wayland screen capture failed ({}). GNOME does not implement the \
             wlr-screencopy protocol xcap needs; install xdg-desktop-portal-gnome \
             and approve the screenshot prompt.",
            failures.join("; ")
        ));
    }

    use image::ImageFormat;
    let monitors = xcap::Monitor::all().map_err(|e| format!("enumerate monitors: {e}"))?;
    let monitor = monitors
        .into_iter()
        .next()
        .ok_or_else(|| "no display available for capture".to_string())?;
    let img = monitor
        .capture_image()
        .map_err(|e| format!("screen capture failed: {e}"))?;
    let mut buf = std::io::Cursor::new(Vec::new());
    image::DynamicImage::from(img)
        .write_to(&mut buf, ImageFormat::Png)
        .map_err(|e| format!("encode PNG: {e}"))?;
    Ok(buf.into_inner())
}

/// Capture the screen for a note snip.
///
/// Hides the main window first (so the app itself isn't in the screenshot),
/// waits briefly for the compositor to settle, captures the screen, then
/// restores + focuses the window so the frontend can render the crop overlay.
/// Returns the full-screen PNG; the frontend crops it to the user's selection.
#[cfg(feature = "snip")]
#[tauri::command]
async fn capture_screen(app: tauri::AppHandle) -> Result<Response, String> {
    let main_win = app
        .get_webview_window("main")
        .ok_or_else(|| "main window not found".to_string())?;
    let _ = main_win.hide();
    // Let the window actually disappear before grabbing pixels.
    tokio::time::sleep(std::time::Duration::from_millis(200)).await;

    let png = capture_primary_monitor_png();

    let _ = main_win.show();
    let _ = main_win.set_focus();
    Ok(Response::new(png?))
}

/// Stub used when built without the `snip` feature (no xcap / pipewire dev).
#[cfg(not(feature = "snip"))]
#[tauri::command]
async fn capture_screen(_app: tauri::AppHandle) -> Result<Response, String> {
    Err("Screen snip is not included in this build (rebuilt without the 'snip' feature).".into())
}

fn main() {
    tauri::Builder::default()
        .manage(ExitState(AtomicBool::new(false)))
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_single_instance::init(|_app, _args, _cwd| {
            // Another instance tried to open — focus existing window
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(
            // Ctrl+Shift+S (Cmd+Shift+S on macOS) triggers a note snip from
            // anywhere; the handler just emits an event the frontend listens
            // for so the crop overlay runs in the webview.
            ShortcutBuilder::new()
                .with_handler(|app, _shortcut, event| {
                    if event.state == ShortcutState::Pressed {
                        let _ = app.emit("snip-requested", ());
                    }
                })
                .build(),
        )
        .invoke_handler(tauri::generate_handler![
            check_deps,
            run_setup,
            capture_screen,
            exit_now
        ])
        .setup(|app| {
            // Resolve data directory
            let data_dir = app
                .path()
                .app_data_dir()
                .map_err(|e| format!("Failed to resolve app data dir: {e}"))?;
            std::fs::create_dir_all(&data_dir)
                .map_err(|e| format!("Failed to create data dir {}: {e}", data_dir.display()))?;

            // Initialise structured logging to file
            init_logging(&data_dir);

            let port = backend_port();
            info!("Starting LifeLogr desktop with backend port {port}");

            // Register the global snip hotkey. Non-fatal if the OS already
            // grabbed it — the toolbar button still works.
            if let Err(e) = app.global_shortcut().register("CommandOrControl+Shift+S") {
                warn!("Could not register snip shortcut (it may be taken by the OS): {e}");
            }

            // Reclaim the port from any stale sidecar left by a previous run,
            // so OUR sidecar can bind it (see reclaim_port).
            reclaim_port(port);

            // Launch Python backend sidecar
            let sidecar_command = app
                .shell()
                .sidecar("lifelogr-backend")
                .map_err(|e| format!("Failed to find sidecar binary: {e}"))?
                .args(["--host", "127.0.0.1", "--port", &port.to_string()])
                .env("DATA_DIR", data_dir.to_string_lossy().to_string())
                .env("APP_ENV", "production");

            let (mut rx, child) = sidecar_command
                .spawn()
                .map_err(|e| format!("Failed to start backend sidecar: {e}"))?;
            // Remember the sidecar PID + own its child handle so shutdown kills
            // the exact process (see SidecarChild / verify_sidecar_owner).
            let child_pid = child.pid();
            app.manage(SidecarChild(Mutex::new(Some(child))));

            // Log sidecar output/stderr
            std::thread::spawn(move || {
                let rt = tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .expect("failed to create tokio runtime for sidecar logging");
                rt.block_on(async {
                    use tauri_plugin_shell::process::CommandEvent;
                    while let Some(event) = rx.recv().await {
                        match event {
                            CommandEvent::Stdout(line) => {
                                info!("[backend] {}", String::from_utf8_lossy(&line))
                            }
                            CommandEvent::Stderr(line) => {
                                warn!("[backend:err] {}", String::from_utf8_lossy(&line))
                            }
                            CommandEvent::Terminated(status) => {
                                info!("[backend] exited: {:?}", status)
                            }
                            CommandEvent::Error(err) => error!("[backend:error] {}", err),
                            _ => {}
                        }
                    }
                });
            });

            // Sidecar health check — TCP probe until backend is ready, then
            // verify (best-effort, Linux) that OUR sidecar owns the port and not
            // a stale process that grabbed it during the bind window.
            let health_port = port;
            std::thread::spawn(move || {
                wait_for_sidecar(health_port);
                verify_sidecar_owner(health_port, child_pid);
            });

            // Permission policy: deny by default. Only device-info requests
            // (the getUserMedia class used by the voice recorder) may be
            // granted. Geolocation, notifications, pointer lock, DRM media
            // keys and everything else are denied — a local journaling app
            // has no use for them, and untrusted content (e.g. an imported
            // journal) must never silently obtain these capabilities.
            //
            // Residual: the pinned webkit2gtk bindings expose no per-device
            // API, so an audio-vs-camera distinction is not possible here; a
            // compromised webview could still request the camera through this
            // one channel. WebRTC is kept off, so no peer connections exist.
            #[cfg(target_os = "linux")]
            {
                let webview_window = app
                    .get_webview_window("main")
                    .ok_or_else(|| "Main webview window not found".to_string())?;
                webview_window
                    .with_webview(|webview| {
                        use webkit2gtk::glib::ObjectExt;
                        use webkit2gtk::{
                            PermissionRequest, PermissionRequestExt, SettingsExt, WebViewExt,
                        };
                        let ctx = webview.inner();

                        // Enable media stream and MediaSource APIs (microphone
                        // capture, media playback). WebRTC peer connections stay
                        // off — nothing in the app establishes one.
                        if let Some(settings) = ctx.settings() {
                            settings.set_enable_media_stream(true);
                            settings.set_enable_mediasource(true);
                            settings.set_enable_webrtc(false);
                        }

                        ctx.connect_permission_request(
                            |_: &webkit2gtk::WebView, req: &PermissionRequest| {
                                if req.is::<webkit2gtk::DeviceInfoPermissionRequest>() {
                                    req.allow();
                                } else {
                                    req.deny();
                                }
                                true
                            },
                        );
                    })
                    .map_err(|e| format!("Failed to set webview media settings: {e}"))?;
            }

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let RunEvent::ExitRequested { api, .. } = event {
                // Never tear down on the event loop: a backup can take minutes
                // and a 5 s blocking poll made a normal close look frozen.
                api.prevent_exit();
                info!("Exit requested — starting the close guard");
                let handle = app_handle.clone();
                std::thread::spawn(move || begin_shutdown(handle));
            }
        });
}
