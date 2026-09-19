#!/usr/bin/env python3
# DEEP RECALL - search the full-context layer, not just the compiled summaries.
#     python3 tools/deepfind.py brake service
#     python3 tools/deepfind.py "winter tune-up"
#
# This is the separate, deliberate door to the COMPLETE record: raw/entries/ and
# data/. Reach for it when a summary will not do and you need the exact words - a
# dispute, a record, documentation, or the full context behind a claim a wiki page
# makes.
#
# Everyday questions use find.py, which searches the summary layer. This is the
# "go deeper" tool. One search engine underneath (find.py --deep); this is its own
# memorable command, because a door nobody can name is a door nobody opens.

import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
os.execvp(sys.executable,
          [sys.executable, os.path.join(here, 'find.py'), '--deep'] + sys.argv[1:])
