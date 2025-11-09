import time
from memory_ipc import connect, read_memory

START_ADDR = 0x80000000
END_ADDR   = 0x80200000
CHUNK_SIZE = 0x100  # 256 bytes per block

def snapshot_memory():
    data = {}
    addr = START_ADDR
    while addr < END_ADDR:
        block = read_memory(addr, CHUNK_SIZE)
        if block:
            data[addr] = block
        addr += CHUNK_SIZE
    return data

def diff_blocks(before, after):
    return [addr for addr in before if addr in after and before[addr] != after[addr]]

def scan_for_text(addr, data):
    text = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in data)
    if any(word in text for word in ["Evenin", "Any t", "Nothing", "?"]):
        print(f"\n🔎 Possible dialogue at 0x{addr:08X}:")
        print(text)

def main():
    print("Connecting to Dolphin...")
    if not connect():
        print("❌ Could not connect. Make sure game is running.")
        return

    print("✅ Connected.")
    input("Stand near villager, NOT in dialogue → press ENTER...")
    before = snapshot_memory()
    print("📸 Snapshot taken.")

    input("Now start talking to the villager → let the dialogue appear → press ENTER...")
    after = snapshot_memory()
    print("📸 Second snapshot taken. Comparing…")

    changed = diff_blocks(before, after)
    print(f"\n✅ Found {len(changed)} changed memory blocks.")

    for addr in changed[:100]:  # first 100 only
        data = read_memory(addr, CHUNK_SIZE)
        if data:
            scan_for_text(addr, data)

if __name__ == "__main__":
    main()
