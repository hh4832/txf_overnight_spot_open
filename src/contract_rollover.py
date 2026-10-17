def consistent(day, night):
    return bool(day and night and day == night and len(str(day)) == 6)
