use pyo3::prelude::*;
use reqwest::Error;

#[pyfunction]
async fn post_it(url: String, json_data: String, headers: String) -> PyResult<()> {
    async fn post(url: String, json_data: String, headers: String) -> Result<(), Error> {
        let client = reqwest::Client::new();

        let response = client
            .post(&url)
            .header("Content-Type", "application/json")
            .header("headers", &headers)
            .body(json_data)
            .send()
            .await?;

        let response_body = response.text().await?;
        println!("Response body:\n{}", response_body);

        Ok(())
    }

    // Call the async function from a synchronous context
    pyo3_asyncio::tokio::into_py(post(url, json_data, headers))
        .map_err(|err| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{}", err)))
}

#[pymodule]
fn rust_py_function(py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(post_it, m)?)?;
    Ok(())
}
