from memcore.sdk import MemCoreClient

client = MemCoreClient("http://localhost:8000", "dev-key")
client.remember(agent_id="me", content="I prefer tea over coffee.")
result = client.recall(agent_id="me", query="what does the user drink")
for hit in result.results:
    print(hit.final, hit.memory.content)
client.close()

