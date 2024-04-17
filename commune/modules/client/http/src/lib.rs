use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Serialize, Deserialize)]
struct Person {
    first_name: String,
    last_name: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct PersonResponse {
    data: String,
    method: String,
    headers: HashMap<String, String>
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let p = Person { 
        first_name: "Foo".into(),
        last_name: "Bar".into(),
    };

    let res = reqwest::Client::new()
        .post("https://httpbin.org/anything")
        .json(&p)
        .send()
        .await?;

    let js = res
        .json::<PersonResponse>()
        .await?;

    let person: Person = serde_json::from_str(&js.data)?;
    println!("{:#?}", person);

    println!("Headers: {:#?}", js.headers);
    Ok(())
}