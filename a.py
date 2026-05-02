from openai import OpenAI
client = OpenAI()
resp = client.chat.completions.create(
model="gpt-oss:20b",
messages=[
{"role": "user", "content": "hello"}
]
)
print(resp.choices[0].message.content)