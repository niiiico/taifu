"""taifu — track JMA typhoon bulletins over time to spot trends.

Japanese weather sites show the *current* typhoon situation and a forecast, but
not how the storm has evolved over the preceding hours/days. This package polls
public JMA feeds on a schedule, archives every payload, and reports whether each
active typhoon is intensifying (central pressure falling / wind rising) or
slowing down / stalling (movement speed dropping).
"""

__version__ = "0.1.0"
