#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::Write;
use std::net::TcpStream;
use std::time::Duration;

use log::{error, info, warn};
use tauri::{Manager, RunEvent};
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

    serde_json::json!({
        "ollama": ollama,
        "gst_plugins_bad": gst_plugins_bad,
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

fn init_logging(data_dir: &std::path::Path) {
    let log_path = data_dir.join("dailybyte-desktop.log");
    let log_file = std::fs::File::create(&log_path).expect("failed to create log file");
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info"))
        .target(env_logger::Target::Pipe(Box::new(log_file)))
        .format(|buf, record| writeln!(buf, "[{} {}] {}", record.level(), record.target(), record.args()))
        .init();
    info!("Logging initialised — writing to {}", log_path.display());
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_single_instance::init(|_app, _args, _cwd| {
            // Another instance tried to open — focus existing window
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .invoke_handler(tauri::generate_handler![check_deps, run_setup])
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
            info!("Starting DailyByte desktop with backend port {port}");

            // Launch Python backend sidecar
            let sidecar_command = app
                .shell()
                .sidecar("diarilinux-backend")
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
            match event {
                RunEvent::ExitRequested { .. } => {
                    info!("Exit requested — shutting down");
                }
                RunEvent::Exit => {
                    info!("Application exiting — sidecar will be killed automatically");
                }
                _ => {}
            }
        });
}
