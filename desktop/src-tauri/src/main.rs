#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::Write;
use std::net::TcpStream;
use std::time::Duration;

use log::{error, info, warn};
use tauri::{Emitter, Manager, RunEvent};
use tauri::ipc::Response;
use tauri_plugin_global_shortcut::{Builder as ShortcutBuilder, GlobalShortcutExt, ShortcutState};
use tauri_plugin_shell::ShellExt;

/// Read backend port from DIARI_PORT env var, defaulting to 18765.
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
        "all_installed": ollama,
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
fn reclaim_port(port: u16) {
    if !port_is_listening(port) {
        return; // port free — nothing to reclaim
    }
    warn!(
        "Port {port} is already in use — reclaiming it from a stale backend sidecar"
    );
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

/// Max time (ms) to wait for the backend to exit on SIGTERM before SIGKILL.
const SIDECAR_GRACE_MS: u64 = 5_000;

/// Gracefully stop the backend sidecar on app exit.
///
/// Complement to [`reclaim_port`]: that runs at *startup* to clear a sidecar
/// left by a previous crashed/killed instance; this runs at *shutdown* so a
/// normal window close actually terminates the backend instead of orphaning it
/// (reparented to systemd --user) holding port 18765 and ~90 MB of RAM. We send
/// SIGTERM first so the backend's FastAPI lifespan teardown runs (stop
/// scheduler, dispose engine), then fall back to SIGKILL if it hasn't exited
/// within the grace window. The listening socket only closes once teardown
/// finishes, so [`port_is_listening`] returning false is the proof that graceful
/// shutdown genuinely completed. Best-effort — `reclaim_port` on the next launch
/// reaps anything still lingering (e.g. if SIGTERM isn't forwarded).
fn shutdown_sidecar(port: u16) {
    if !port_is_listening(port) {
        return; // backend already gone
    }
    info!("Stopping backend sidecar on port {port} (SIGTERM)");
    let _ = std::process::Command::new("pkill")
        .args(["-TERM", "-f", "lifelogr-backend"])
        .status();
    for _ in 0..(SIDECAR_GRACE_MS / 100) {
        if !port_is_listening(port) {
            info!("Backend sidecar stopped gracefully");
            return;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    warn!(
        "Backend sidecar did not exit within {SIDECAR_GRACE_MS} ms — sending SIGKILL"
    );
    let _ = std::process::Command::new("pkill")
        .args(["-KILL", "-f", "lifelogr-backend"])
        .status();
    for _ in 0..20 {
        if !port_is_listening(port) {
            info!("Backend sidecar killed");
            return;
        }
        std::thread::sleep(Duration::from_millis(150));
    }
    warn!("Backend sidecar still on port {port} after SIGKILL (next launch will reclaim it)");
}

fn init_logging(data_dir: &std::path::Path) {
    let log_path = data_dir.join("lifelogr-desktop.log");
    let log_file = std::fs::File::create(&log_path).expect("failed to create log file");
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info"))
        .target(env_logger::Target::Pipe(Box::new(log_file)))
        .format(|buf, record| writeln!(buf, "[{} {}] {}", record.level(), record.target(), record.args()))
        .init();
    info!("Logging initialised — writing to {}", log_path.display());
}

/// Capture the first available monitor as a PNG byte buffer.
///
/// We grab the first monitor rather than detecting "primary" so the call works
/// across xcap versions whose monitor-selection API differs. For the typical
/// single-monitor setup this is the whole screen.
#[cfg(feature = "snip")]
fn capture_primary_monitor_png() -> Result<Vec<u8>, String> {
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
        .invoke_handler(tauri::generate_handler![check_deps, run_setup, capture_screen])
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
                .args([
                    "--host", "127.0.0.1",
                    "--port", &port.to_string(),
                ])
                .env("DATA_DIR", data_dir.to_string_lossy().to_string())
                .env("APP_ENV", "production");

            let (mut rx, _child) = sidecar_command
                .spawn()
                .map_err(|e| format!("Failed to start backend sidecar: {e}"))?;

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
                            CommandEvent::Stdout(line) => info!("[backend] {}", String::from_utf8_lossy(&line)),
                            CommandEvent::Stderr(line) => warn!("[backend:err] {}", String::from_utf8_lossy(&line)),
                            CommandEvent::Terminated(status) => info!("[backend] exited: {:?}", status),
                            CommandEvent::Error(err) => error!("[backend:error] {}", err),
                            _ => {}
                        }
                    }
                });
            });

            // Sidecar health check — TCP probe until backend is ready
            let health_port = port;
            std::thread::spawn(move || {
                wait_for_sidecar(health_port);
            });

            // SAFETY: Auto-grant permission requests (microphone, camera, geolocation).
            // This is correct for a local-only desktop journaling app — all content is
            // user-created and stored locally. No remote content is loaded, so there is
            // no risk of malicious sites abusing these permissions.
            #[cfg(target_os = "linux")]
            {
                let webview_window = app.get_webview_window("main")
                    .ok_or_else(|| "Main webview window not found".to_string())?;
                webview_window.with_webview(|webview| {
                    use webkit2gtk::{PermissionRequest, PermissionRequestExt, SettingsExt, WebViewExt};
                    let ctx = webview.inner();

                    // Explicitly enable media stream and MediaSource APIs
                    if let Some(settings) = ctx.settings() {
                        settings.set_enable_media_stream(true);
                        settings.set_enable_mediasource(true);
                        settings.set_enable_webrtc(true);
                    }

                    // Auto-grant all permission requests (microphone, camera, geolocation, etc.)
                    ctx.connect_permission_request(|_: &webkit2gtk::WebView, req: &PermissionRequest| {
                        req.allow();
                        true
                    });
                }).map_err(|e| format!("Failed to set webview media settings: {e}"))?;
            }

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|_app_handle, event| {
            if let RunEvent::ExitRequested { .. } = event {
                info!("Exit requested — shutting down backend sidecar");
                shutdown_sidecar(backend_port());
            }
        });
}
