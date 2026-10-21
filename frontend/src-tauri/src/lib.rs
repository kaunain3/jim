use serde::Serialize;

#[derive(Serialize)]
struct Greeting {
    message: String,
    character_count: usize,
}

#[tauri::command]
fn greet(name: &str) -> Greeting {
    Greeting {
        message: format!("Hello, {}! This message came from Rust.", name),
        character_count: name.chars().count(),
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![greet])
        .run(tauri::generate_context!())
        .expect("error while building tauri application");
}