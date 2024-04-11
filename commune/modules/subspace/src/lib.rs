


use pyo3::prelude::*;
use substrate_subxt::{ClientBuilder, DefaultNodeRuntime};
use std::collections::HashMap;

#[pyfunction]
async fn create_substrate_interface(params: HashMap<String, PyObject>) -> PyResult<()> {
    let url = params.get("url").ok_or_else(|| pyo3::exceptions::PyValueError::new_err("Missing 'url' parameter"))?.extract::<String>()?;
    let websocket = params.get("websocket").map(|v| v.extract::<String>().ok()).flatten();
    let ss58_format = params.get("ss58_format").map(|v| v.extract::<u32>().ok()).flatten();
    let type_registry = params.get("type_registry").map(|v| v.extract::<String>().ok()).flatten();
    let type_registry_preset = params.get("type_registry_preset").map(|v| v.extract::<String>().ok()).flatten();
    let cache_region = params.get("cache_region").map(|v| v.extract::<String>().ok()).flatten();
    let runtime_config = params.get("runtime_config").map(|v| v.extract::<String>().ok()).flatten();
    let ws_options = params.get("ws_options").map(|v| v.extract::<String>().ok()).flatten();
    let auto_discover = params.get("auto_discover").map(|v| v.extract::<bool>().ok()).flatten();
    let auto_reconnect = params.get("auto_reconnect").map(|v| v.extract::<bool>().ok()).flatten();

    let substrate = ClientBuilder::<DefaultNodeRuntime>::new()
        .set_url(url)
        .set_websocket(websocket)
        .set_ss58_format(ss58_format)
        .set_type_registry(type_registry)
        .set_type_registry_preset(type_registry_preset)
        .set_cache_region(cache_region)
        .set_runtime_config(runtime_config)
        .set_ws_options(ws_options)
        .set_auto_discover(auto_discover)
        .set_auto_reconnect(auto_reconnect)
        .build()
        .await?;

    println!("{:?}", substrate);

    Ok(())
}

#[pymodule]
fn my_module(py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(create_substrate_interface, m)?)?;

    Ok(())
}
