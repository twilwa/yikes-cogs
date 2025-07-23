twitterfix/twitterfix.py
                                if summary_match:
                                    # Handle escaped quotes and newlines in summary
                                    summary = summary_match.group(1)
                                    summary = summary.replace(r'\"', '"').replace(r'\n', '\n')
Contributor
@sourcery-ai sourcery-ai bot 2 minutes ago
suggestion (bug_risk): Manual unescaping of summary may not cover all escape sequences.

This approach misses other escape sequences like unicode or tabs. Using codecs.decode or json.loads would ensure all standard escapes are handled.

Suggested implementation:

                                    # Handle all standard escape sequences in summary
                                    import json
                                    summary = summary_match.group(1)
                                    try:
                                        summary = json.loads(f'"{summary}"')
                                    except Exception:
                                        # Fallback to original if decoding fails
                                        pass
                                    structured_output["thread-summary"] = summary
If the import json statement is already present at the top of the file, you can remove the new import inside the function and just use json.loads directly.
