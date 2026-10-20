"""Unit tests never touch the network: the v4 media resolution (pipeline.build -> mediaplan.resolve) runs offline,
so director media cues render the text card they replaced. Tests that exercise picking pass their own selector,
which resolve() always runs. Set here (process env) so `python -m reel_director` subprocesses inherit it."""
import os

os.environ["RD_MEDIA_OFFLINE"] = "1"
