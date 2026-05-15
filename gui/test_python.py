import textwrap


messages = ["Davian absolutely destroys Baba Lysaga with a huge critical hit on his sneak attack",
            "Baba Lysaga flies around and shoots Davian with her Poison Darts"]


log_y = 0
max_log_w = 20 - 2          # 2 px breathing room before the panel edge
for msg in messages:
    #clipped = _fit(msg, max_log_w, self.font_sm)
    wrapped = textwrap.wrap(msg, max_log_w, subsequent_indent='  ')
    print("msg is ", msg)
    print("wrapped is ", wrapped)
    if len(wrapped) > 100 : exit 
    for i in wrapped: 
        print(i)
    #txt(msg, lx, log_y)



