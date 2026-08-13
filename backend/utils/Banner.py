def print_banner():
    ORANGE = "\033[38;5;208m"
    WHITE = "\033[97m"
    RESET = "\033[0m"
    SPLIT = 32  # exact column where "PEACH" glyphs end on every line

    def striped_line(width=70):
        out = ""
        for i in range(width):
            color = ORANGE if (i // 2) % 2 == 0 else WHITE
            out += f"{color}={RESET}"
        return out

    lines = [
        " ____  ____    __    ___  _   _      ____  ____    __    ____  ____  _  _  ___ ",
        "(  _ \\( ___)  /__\\  / __)( )_( ) ___(_  _)(  _ \\  /__\\  (  _ \\(_  _)( \\( )/ __)",
        " )___/ )__)  /(__)\\( (__  ) _ ( (___) )(   )   / /(__)\\  )(_) )_)(_  )  (( (_-.",
        "(__)  (____)(__)(__)\\___)(_) (_)     (__) (_)\\_)(__)(__)(____/(____)(_)\\_)\\___/",
    ]

    print()
    print(striped_line())
    print()
    for line in lines:
        peach, trading = line[:SPLIT], line[SPLIT:]
        print(f"{ORANGE}{peach}{RESET}{trading}")
    print(f"                   🍑 -- {ORANGE}PEACH{RESET}-TRADING BACKEND -- 🍑")
    print()
    print(striped_line())
    print()