import requests
import csv

# ← Never share this
api_key = "AIQNZRqrZivb1Hzyk6FvYAx2Nrej9Wmv7SgFJ0AENRzh1MO8sKX7JQQJ99BBACYeBjFXJ3w3AAABACOGirov"
endpoint = "https://dataforest-azure-model.openai.azure.com"
vectorstore_id = "vs_Bd7lDWAH9iLC2gh3ngy282vx"
api_version = "2024-05-01-preview"

all_files = []
after = None

while True:
    url = f"{endpoint}/openai/vectorstores/{vectorstore_id}/files?api-version={api_version}"
    if after:
        url += f"&after={after}"

    headers = {
        "api-key": api_key,
        "Content-Type": "application/json"
    }

    response = requests.get(url, headers=headers)
    response.raise_for_status()
    data = response.json()

    all_files.extend(data.get("data", []))
    if not data.get("has_more"):
        break

    after = data["data"][-1]["id"]

# Print file list

for file in all_files:
    print(f"{file['id']} | {file['status']} | {file['created_at']}")

# Optional: Save to CSV
with open("vector_files.csv", "w", newline="") as csvfile:
    writer = csv.writer(csvfile)
    writer.writerow(["File ID", "Status", "Created At"])
    for file in all_files:
        writer.writerow([file["id"], file["status"], file["created_at"]])
