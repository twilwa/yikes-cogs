[2025-07-22 23:54:38] [ERROR] red: Package loading failed
Traceback (most recent call last):
  File "/data/venv/lib/python3.11/site-packages/redbot/core/core_commands.py", line 189, in _load
    await bot.load_extension(spec)
  File "/data/venv/lib/python3.11/site-packages/redbot/core/bot.py", line 1708, in load_extension
    lib = spec.loader.load_module()
          ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "<frozen importlib._bootstrap_external>", line 605, in _check_name_wrapper
  File "<frozen importlib._bootstrap_external>", line 1120, in load_module
  File "<frozen importlib._bootstrap_external>", line 945, in load_module
  File "<frozen importlib._bootstrap>", line 290, in _load_module_shim
  File "<frozen importlib._bootstrap>", line 721, in _load
  File "<frozen importlib._bootstrap>", line 690, in _load_unlocked
  File "<frozen importlib._bootstrap_external>", line 940, in exec_module
  File "<frozen importlib._bootstrap>", line 241, in _call_with_frames_removed
  File "/data/cogs/CogManager/cogs/twitterfix/__init__.py", line 4, in <module>
    from .twitterfix import TwitterFix
  File "/data/cogs/CogManager/cogs/twitterfix/twitterfix.py", line 330
    import json as _json
SyntaxError: expected 'except' or 'finally' block
