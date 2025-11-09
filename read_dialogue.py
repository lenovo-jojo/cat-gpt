from memory_ipc import connect, read_memory

DIALOGUE_ADDR = 0x803F14F0  # start of current villager dialogue
MAX_LEN = 200  # read first 200 bytes of text

AC_ENCODING = {   # basic set – we can extend it
    0x00: '',
    0x20: ' ', 0x21: '!', 0x22: '"', 0x23: '#',
    0x2C: ',', 0x2E: '.', 0x3F: '?',
    0x41: 'A', 0x42: 'B', 0x43: 'C', 0x44: 'D',
    0x45: 'E', 0x46: 'F', 0x47: 'G', 0x48: 'H',
    0x49: 'I', 0x4A: 'J', 0x4B: 'K', 0x4C: 'L',
    0x4D: 'M', 0x4E: 'N', 0x4F: 'O',
    0x50: 'P', 0x51: 'Q', 0x52: 'R', 0x53: 'S',
    0x54: 'T', 0x55: 'U', 0x56: 'V', 0x57: 'W',
    0x58: 'X', 0x59: 'Y', 0x5A: 'Z',
    0x61: 'a', 0x62: 'b', 0x63: 'c', 0x64: 'd',
    0x65: 'e', 0x66: 'f', 0x67: 'g', 0x68: 'h',
    0x69: 'i', 0x6A: 'j', 0x6B: 'k', 0x6C: 'l',
    0x6D: 'm', 0x6E: 'n', 0x6F: 'o',
    0x70: 'p', 0x71: 'q', 0x72: 'r', 0x73: 's',
    0x74: 't', 0x75: 'u', 0x76: 'v', 0x77: 'w',
    0x78: 'x', 0x79: 'y', 0x7A: 'z',
    0x80: '…', 0x8E: "'", 0x9A: '♥'
}

def decode_dialogue(raw):
    result = []
    for b in raw:
        if b == 0x00:  # end of string
            break
        result.append(AC_ENCODING.get(b, '?'))
    return ''.join(result)

def main():
    print("Connecting...")
    if not connect():
        print("❌ Could not connect to Dolphin.")
        return

    raw = read_memory(DIALOGUE_ADDR, MAX_LEN)
    if raw:
        print("Raw bytes:", raw[:50])
        print("Decoded text:", decode_dialogue(raw))
    else:
        print("Couldn't read memory.")

if __name__ == "__main__":
    main()
