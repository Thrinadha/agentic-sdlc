---
id: REQ-404
title: Safe division helper
scenario: failing-calculator
---
Add a `divide(a, b)` helper to the calculator module. Dividing by zero must raise `ValueError` with a clear
message instead of returning infinity or crashing with `ZeroDivisionError`.

<!-- Demo scenario: the recorded coder answer never fixes the bug, so automatic recovery runs out, the
     escalation gate is rejected by the unattended policy, an alert fires and `sdlc debug` explains why. -->
