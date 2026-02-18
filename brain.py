import json
import os
import threading
import requests

CHAT_FILE = "chat_history.json"
MEMORY_FILE = "memory.json"
EMOTION_FILE = "emotion.txt"

GROQ_API_KEY = "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"

# ---------- Default emotion ----------
DEFAULT_EMOTION = {
    "mood": "neutral",
    "stress": 3,
    "trust_in_user": 5,
    "current_goal": "get to know the user"
}

# ---------- Groq Chat ----------
def groq_chat(messages, temperature=0.8, model="llama-3.1-8b-instant"):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        print("Groq API error:", e)
        return "Sorry, I couldn't generate a response."

# ---------- Emotion helpers ----------
def clamp(n, lo=0, hi=10):
    try:
        return max(lo, min(hi, int(n)))
    except:
        return lo

def load_emotion():
    if not os.path.exists(EMOTION_FILE):
        return DEFAULT_EMOTION.copy()

    try:
        with open(EMOTION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except:
        return DEFAULT_EMOTION.copy()

    # validate + repair
    return {
        "mood": str(data.get("mood", DEFAULT_EMOTION["mood"])),
        "stress": clamp(data.get("stress", DEFAULT_EMOTION["stress"])),
        "trust_in_user": clamp(data.get("trust_in_user", DEFAULT_EMOTION["trust_in_user"])),
        "current_goal": str(data.get("current_goal", DEFAULT_EMOTION["current_goal"]))
    }

def save_emotion(state):
    with open(EMOTION_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

# ---------- File helpers ----------
def read_file(name):
    if not os.path.exists(name):
        return ""
    with open(name, "r", encoding="utf-8") as f:
        return f.read()

def load_chat():
    try:
        with open(CHAT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def save_chat(conversation):
    with open(CHAT_FILE, "w", encoding="utf-8") as f:
        json.dump(conversation, f, indent=2)

def load_memories():
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def save_memories(memories):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memories, f, indent=2)

def memory_to_prompt_text(memories):
    if not memories:
        return "No significant memories yet."
    lines = []
    for m in memories:
        tag_text = ", ".join(m.get("tags", []))
        lines.append(f"[Imp {m['importance']} | {tag_text}] {m['summary'][:120]}")
    return "\n".join(lines)

# ---------- Post turn AI ----------
def process_post_turn(buffer_text, current_emotion):
    prompt = f"""
Summarize events shortly, score importance 1-10,
add 1-3 tags, and update emotional state realistically.

Current emotional state:
{json.dumps(current_emotion, indent=2)}

Return ONLY valid JSON:

{{
 "summary": "...",
 "importance": 5,
 "tags": ["a","b"],
 "emotion": {{
   "mood": "...",
   "stress": 0-10,
   "trust_in_user": 0-10,
   "current_goal": "..."
 }}
}}

Events:
{buffer_text}
"""

    try:
        raw = groq_chat([{"role": "user", "content": prompt}], temperature=0.5)
        data = json.loads(raw)

        # validate emotion block
        emo = data.get("emotion", {})
        data["emotion"] = {
            "mood": str(emo.get("mood", current_emotion["mood"])),
            "stress": clamp(emo.get("stress", current_emotion["stress"])),
            "trust_in_user": clamp(emo.get("trust_in_user", current_emotion["trust_in_user"])),
            "current_goal": str(emo.get("current_goal", current_emotion["current_goal"]))
        }

        return data

    except Exception as e:
        print("Error in post-turn AI:", e)
        print("Raw:", raw)
        return None

# ---------- ChatBrain ----------
class ChatBrain:
    MAX_CONTEXT = 16

    def __init__(self):
        self.character_sheet = read_file("mina_prompt.txt")
        self.emotion = load_emotion()

        self.memories = load_memories()
        self.summary_buffer = []
        self.turn_counter = 0

        memory_text = memory_to_prompt_text(self.memories)
        system_prompt = (
            self.character_sheet
            + "\nLong-term memory:\n" + memory_text
            + "\nCurrent emotional state:\n" + json.dumps(self.emotion, indent=2)
            + """
Behavior rules:
- High stress (>7): shorter replies, defensive
- Low trust (<3): cautious
- High trust (>7): warm
- Goal influences topic focus
"""
        )

        old_chat = load_chat()
        if old_chat:
            self.conversation = old_chat
            self.conversation[0]["content"] = system_prompt
        else:
            self.conversation = [{"role": "system", "content": system_prompt}]

    # ---------- main chat ----------
    def process_user_message(self, user_input):
        self.conversation.append({"role": "user", "content": user_input})
        save_chat(self.conversation)

        reply = groq_chat(self.conversation, temperature=0.9)
        self.conversation.append({"role": "assistant", "content": reply})

        if len(self.conversation) > self.MAX_CONTEXT:
            self.conversation = [self.conversation[0]] + self.conversation[-(self.MAX_CONTEXT-1):]

        self.summary_buffer.append(f"User: {user_input}")
        self.summary_buffer.append(f"Mina: {reply}")

        self.turn_counter += 1
        if self.turn_counter >= 4:
            buffer_text = "\n".join(self.summary_buffer)
            self.summary_buffer.clear()
            self.turn_counter = 0
            threading.Thread(
                target=self._background_memory_update,
                args=(buffer_text,),
                daemon=True
            ).start()

        return [reply]

    # ---------- background memory update ----------
    def _background_memory_update(self, buffer_text):
        data = process_post_turn(buffer_text, self.emotion)
        if not data:
            return

        self.memories.append({
            "summary": data["summary"],
            "importance": data["importance"],
            "tags": data["tags"]
        })

        self.memories = sorted(self.memories, key=lambda m: m["importance"], reverse=True)[:50]
        save_memories(self.memories)

        self.emotion = data["emotion"]
        save_emotion(self.emotion)

        memory_text = memory_to_prompt_text(self.memories)
        self.conversation[0]["content"] = (
            self.character_sheet
            + "\nLong-term memory:\n" + memory_text
            + "\nCurrent emotional state:\n" + json.dumps(self.emotion, indent=2)
        )
