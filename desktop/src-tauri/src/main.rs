#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::{Manager, RunEvent};
use tauri_plugin_shell::ShellExt;

const BACKEND_PORT: u16 = 18765;

/// Check which system dependencies are installed.
#[tauri::command]
fn check_deps() -> serde_json::Value {
    let tesseract = std::process::Command::new("tesseract")
        .arg("--version")
        .output()
        .is_ok();

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
        "tesseract": tesseract,
        "ollama": ollama,
        "gst_plugins_bad": gst_plugins_bad,
        "all_installed": tesseract && ollama,
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
                .expect("failed to resolve app data dir");
            std::fs::create_dir_all(&data_dir).expect("failed to create data dir");

            // Launch Python backend sidecar
            let sidecar_command = app
                .shell()
                .sidecar("diarilinux-backend")
                .expect("failed to find sidecar binary")
                .args([
                    "--host", "127.0.0.1",
                    "--port", &BACKEND_PORT.to_string(),
                ])
                .env("DATA_DIR", data_dir.to_string_lossy().to_string())
                .env("APP_ENV", "production");

            let (mut rx, _child) = sidecar_command.spawn().expect("failed to start backend sidecar");

            // Log sidecar output/stderr to help debug startup issues
            std::thread::spawn(move || {
                let rt = tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .unwrap();
                rt.block_on(async {
                    use tauri_plugin_shell::process::CommandEvent;
                    while let Some(event) = rx.recv().await {
                        match event {
                            CommandEvent::Stdout(line) => eprintln!("[backend] {}", String::from_utf8_lossy(&line)),
                            CommandEvent::Stderr(line) => eprintln!("[backend:err] {}", String::from_utf8_lossy(&line)),
                            CommandEvent::Terminated(status) => eprintln!("[backend] exited: {:?}", status),
                            CommandEvent::Error(err) => eprintln!("[backend:error] {}", err),
                            _ => {}
                        }
                    }
                });
            });

            // Enable WebKit media features and auto-grant permission requests (microphone/camera) on Linux
            #[cfg(target_os = "linux")]
            {
                let webview_window = app.get_webview_window("main").unwrap();
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
                }).expect("failed to set webview media settings");
            }

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|_app_handle, event| {
            if let RunEvent::Exit = event {
                // Sidecar is killed automatically when the app exits
            }
        });
}
