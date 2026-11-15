OFFLINE DECISION MODEL EXPERIMENT

This trains a small categorical Naive Bayes model using recorded combat and recovery key presses. It uses Python's standard library and never sends input to a game. It is not Laya; it is a simple benchmark to test whether the signals have useful predictive power.

1. Put train_decisions.py next to your other scripts. Your recording folder must contain decision_replay_with_abilities.csv from the previous ability-analysis step. Run ability_states.py analyze if necessary. The CSV needs the pre-input state_frame, state_unix_ns, action_unix_ns, state_age_ms, the health/combat/rage/target fields, the three icon appearance fields, and observed_action.

2. From PowerShell in the scripts folder, replace the example folder name:

.\.venv\Scripts\python train_decisions.py .\recording_FOLDER

The output is a decision_training subfolder in that recording. report.json describes training and test action counts, unseen classes, overall and balanced accuracy, and per-action recall. test_predictions.csv compares model and most-common-action baseline to your recorded inputs. model.json is the fitted model and can be loaded by later Python code. Re-running overwrites these output files only.

The script sorts by action time, holds out the last 25% for testing, and leaves a two-second gap between train and test to reduce overlap. A split within one session is only an initial check. An independent recording would be a stronger test. If data is insufficient, the script reports it rather than claiming a result. The gap can be adjusted with --gap-seconds, but shrinking it increases similarity between training and test examples.

This is conditional imitation: among recorded combat/recovery key presses it predicts which key you pressed. It doesn't learn when to act because idle periods are absent, and it excludes movement, targeting and right-clicks. Key presses may repeat, fail or be suboptimal. Accuracy measures agreement with your actions, not game success, ability usability, or safety. Target/health and icon values are estimates; capture timestamps may lag the game. Several classes may be absent from training or test, making results unreliable. Do not use the model as an autonomous controller.
