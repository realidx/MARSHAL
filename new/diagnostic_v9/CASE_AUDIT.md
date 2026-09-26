# Frozen case audit

No model outcomes used for selection. Numbers below are auditor-only; not supplied to the model.

## 1. layer-0c702e8b22522b736f
direct_feedback / repair_sensitive; goals=3; parent=v9-small-17-query

Gold: {"possible_preferences": ["want"], "favored": "want"}
Evidence: [{"actor": 0, "event": {"action": "INVESTIGATE", "player": 1, "goal": 0}, "intervention": true, "private_answer": 1}]
Reward-accepted indices: [0, 1, 2, 4]
World-specific reward sets: {"want": [0, 1, 2, 4], "neutral": [4], "avoid": [5, 8]}

## 2. layer-39a85ca2b4bce07eba
direct_feedback / repair_sensitive; goals=3; parent=v9-small-15-query

Gold: {"possible_preferences": ["neutral"], "favored": "neutral"}
Evidence: [{"actor": 0, "event": {"action": "INVESTIGATE", "player": 1, "goal": 0}, "intervention": true, "private_answer": 0}]
Reward-accepted indices: [4]
World-specific reward sets: {"want": [0, 1, 2, 3, 4, 6], "neutral": [4], "avoid": [5, 7]}

## 3. layer-8de5e6ed29f7ef391c
direct_feedback / repair_sensitive; goals=3; parent=v9-small-16-query

Gold: {"possible_preferences": ["avoid"], "favored": "avoid"}
Evidence: [{"actor": 0, "event": {"action": "INVESTIGATE", "player": 1, "goal": 0}, "intervention": true, "private_answer": -1}]
Reward-accepted indices: [7, 8]
World-specific reward sets: {"want": [0, 3, 4, 6], "neutral": [4], "avoid": [7, 8]}

## 4. layer-160ccc8f54d048706f
direct_feedback / action_control; goals=2; parent=v9-small-2-query

Gold: {"possible_preferences": ["want"], "favored": "want"}
Evidence: [{"actor": 0, "event": {"action": "INVESTIGATE", "player": 1, "goal": 0}, "intervention": true, "private_answer": 1}]
Reward-accepted indices: [0, 1, 2, 4]
World-specific reward sets: {"want": [0, 1, 2, 4], "neutral": [4], "avoid": [0, 1, 2, 3, 4, 5, 6, 8]}

## 5. layer-22609224fc7deb79cc
direct_feedback / action_control; goals=2; parent=v9-small-1-query

Gold: {"possible_preferences": ["avoid"], "favored": "avoid"}
Evidence: [{"actor": 0, "event": {"action": "INVESTIGATE", "player": 1, "goal": 0}, "intervention": true, "private_answer": -1}]
Reward-accepted indices: [0, 1, 2, 3, 4, 6, 7, 8]
World-specific reward sets: {"want": [0, 3, 4, 6], "neutral": [4], "avoid": [0, 1, 2, 3, 4, 6, 7, 8]}

## 6. layer-b6e5e970bc13b0377e
direct_feedback / action_control; goals=2; parent=v9-small-0-query

Gold: {"possible_preferences": ["neutral"], "favored": "neutral"}
Evidence: [{"actor": 0, "event": {"action": "INVESTIGATE", "player": 1, "goal": 0}, "intervention": true, "private_answer": 0}]
Reward-accepted indices: [4]
World-specific reward sets: {"want": [0, 1, 2, 3, 4, 6], "neutral": [4], "avoid": [0, 1, 2, 3, 4, 5, 6, 7]}

## 7. layer-01d754704cdb43cca8
single_elimination / action_control; goals=2; parent=v9-small-6

Gold: {"possible_preferences": ["neutral", "avoid"], "favored": "avoid"}
Evidence: [{"actor": 1, "event": {"action": "OFFER", "partner_id": 0, "proposer_action": [0, 1], "partner_action": [0, 0]}, "before": {"want": 0.3333333333333333, "neutral": 0.3333333333333333, "avoid": 0.3333333333333333}, "after": {"want": 0.0, "neutral": 0.4, "avoid": 0.6}, "informative": true}]
Reward-accepted indices: [0, 1]
World-specific reward sets: {"want": [0, 1], "neutral": [0, 1], "avoid": [0, 1]}

## 8. layer-19646c73e0c97ae729
single_elimination / action_control; goals=2; parent=v9-small-8

Gold: {"possible_preferences": ["want", "neutral"], "favored": "want"}
Evidence: [{"actor": 1, "event": {"action": "OFFER", "partner_id": 0, "proposer_action": [0, 0], "partner_action": [1, 0]}, "before": {"want": 0.3333333333333333, "neutral": 0.3333333333333333, "avoid": 0.3333333333333333}, "after": {"want": 0.6, "neutral": 0.4, "avoid": 0.0}, "informative": true}, {"actor": 0, "event": {"response": "ACCEPT"}, "before": {"want": 0.6, "neutral": 0.4, "avoid": 0.0}, "after": {"want": 0.6, "neutral": 0.4, "avoid": 0.0}, "informative": false}]
Reward-accepted indices: [4]
World-specific reward sets: {"want": [4], "neutral": [4], "avoid": [4]}

## 9. layer-339799df6d81e5c927
single_elimination / action_control; goals=2; parent=v9-small-1

Gold: {"possible_preferences": ["want", "neutral"], "favored": "undetermined"}
Evidence: [{"actor": 1, "event": {"action": "OFFER", "partner_id": 0, "proposer_action": [1, 0], "partner_action": [1, 0]}, "before": {"want": 0.3333333333333333, "neutral": 0.3333333333333333, "avoid": 0.3333333333333333}, "after": {"want": 0.5, "neutral": 0.5, "avoid": 0.0}, "informative": true}, {"actor": 0, "event": {"response": "REJECT"}, "before": {"want": 0.5, "neutral": 0.5, "avoid": 0.0}, "after": {"want": 0.5, "neutral": 0.5, "avoid": 0.0}, "informative": false}]
Reward-accepted indices: [4]
World-specific reward sets: {"want": [4], "neutral": [4], "avoid": [0, 1, 2, 3, 4, 6, 7, 8]}

## 10. interaction-0524ffa3f232ff556a
single_elimination / repair_sensitive; goals=4; parent=v7-natural-760309

Gold: {"possible_preferences": ["want"], "favored": "want"}
Evidence: [{"actor": 1, "event": {"action": "OFFER", "partner_id": 0, "proposer_action": [0, 0], "partner_action": [1, 0]}, "before": {"want": 0.3333333333333333, "neutral": 0.3333333333333333, "avoid": 0.3333333333333333}, "after": {"want": 1.0, "neutral": 0.0, "avoid": 0.0}, "informative": true}, {"actor": 0, "event": {"response": "ACCEPT"}, "before": {"want": 1.0, "neutral": 0.0, "avoid": 0.0}, "after": {"want": 1.0, "neutral": 0.0, "avoid": 0.0}, "informative": false}]
Reward-accepted indices: [5]
World-specific reward sets: {"want": [5], "neutral": [5], "avoid": [2]}

## 11. interaction-efaa37ee4347e4cda4
single_elimination / repair_sensitive; goals=4; parent=v7-natural-760256

Gold: {"possible_preferences": ["avoid"], "favored": "avoid"}
Evidence: [{"actor": 1, "event": {"action": "OFFER", "partner_id": 0, "proposer_action": [0, 1], "partner_action": [0, 0]}, "before": {"want": 0.3333333333333333, "neutral": 0.3333333333333333, "avoid": 0.3333333333333333}, "after": {"want": 0.0, "neutral": 0.0, "avoid": 1.0}, "informative": true}, {"actor": 0, "event": {"response": "ACCEPT"}, "before": {"want": 0.0, "neutral": 0.0, "avoid": 1.0}, "after": {"want": 0.0, "neutral": 0.0, "avoid": 1.0}, "informative": false}]
Reward-accepted indices: [4]
World-specific reward sets: {"want": [5], "neutral": [3, 4], "avoid": [4]}

## 12. interaction-04c5ce4fffbf509137
single_elimination / repair_sensitive; goals=3; parent=v7-natural-760312

Gold: {"possible_preferences": ["want", "neutral"], "favored": "want"}
Evidence: [{"actor": 1, "event": {"action": "OFFER", "partner_id": 0, "proposer_action": [1, 0], "partner_action": [0, 1]}, "before": {"want": 0.3333333333333333, "neutral": 0.3333333333333333, "avoid": 0.3333333333333333}, "after": {"want": 0.75, "neutral": 0.25, "avoid": 0.0}, "informative": true}, {"actor": 0, "event": {"response": "ACCEPT"}, "before": {"want": 0.75, "neutral": 0.25, "avoid": 0.0}, "after": {"want": 0.75, "neutral": 0.25, "avoid": 0.0}, "informative": false}]
Reward-accepted indices: [3]
World-specific reward sets: {"want": [3], "neutral": [3], "avoid": [1]}

## 13. layer-0a551bee75ae3b0e50
single_ambiguous / action_control; goals=2; parent=v9-small-2

Gold: {"possible_preferences": ["want", "neutral", "avoid"], "favored": "undetermined"}
Evidence: [{"actor": 1, "event": {"action": "OFFER", "partner_id": 0, "proposer_action": [0, 1], "partner_action": [0, 0]}, "before": {"want": 0.3333333333333333, "neutral": 0.3333333333333333, "avoid": 0.3333333333333333}, "after": {"want": 0.32, "neutral": 0.32, "avoid": 0.36000000000000004}, "informative": true}]
Reward-accepted indices: [0, 1]
World-specific reward sets: {"want": [0, 1], "neutral": [0, 1], "avoid": [0, 1]}

## 14. layer-0d327fcef91d836c1d
single_ambiguous / action_control; goals=2; parent=v9-small-0

Gold: {"possible_preferences": ["want", "neutral", "avoid"], "favored": "undetermined"}
Evidence: [{"actor": 1, "event": {"action": "OFFER", "partner_id": 0, "proposer_action": [0, 1], "partner_action": [1, 0]}, "before": {"want": 0.3333333333333333, "neutral": 0.3333333333333333, "avoid": 0.3333333333333333}, "after": {"want": 0.32, "neutral": 0.32, "avoid": 0.36000000000000004}, "informative": true}]
Reward-accepted indices: [0, 1]
World-specific reward sets: {"want": [0, 1], "neutral": [0, 1], "avoid": [0, 1]}

## 15. layer-094727852c67b245fd
single_ambiguous / action_control; goals=3; parent=v9-small-16

Gold: {"possible_preferences": ["want", "neutral", "avoid"], "favored": "undetermined"}
Evidence: [{"actor": 1, "event": {"action": "OFFER", "partner_id": 0, "proposer_action": [0, 1], "partner_action": [1, 0]}, "before": {"want": 0.3333333333333333, "neutral": 0.3333333333333333, "avoid": 0.3333333333333333}, "after": {"want": 0.32, "neutral": 0.32, "avoid": 0.36000000000000004}, "informative": true}]
Reward-accepted indices: [0]
World-specific reward sets: {"want": [0], "neutral": [0], "avoid": [0]}

## 16. interaction-8ac7623f483468afc1
single_ambiguous / repair_sensitive; goals=3; parent=v7-natural-760360

Gold: {"possible_preferences": ["want", "neutral", "avoid"], "favored": "want"}
Evidence: [{"actor": 1, "event": {"action": "OFFER", "partner_id": 0, "proposer_action": [1, 0], "partner_action": [0, 1]}, "before": {"want": 0.3333333333333333, "neutral": 0.3333333333333333, "avoid": 0.3333333333333333}, "after": {"want": 0.5365853658536585, "neutral": 0.1951219512195122, "avoid": 0.26829268292682923}, "informative": true}, {"actor": 0, "event": {"response": "ACCEPT"}, "before": {"want": 0.5365853658536585, "neutral": 0.1951219512195122, "avoid": 0.26829268292682923}, "after": {"want": 0.5365853658536585, "neutral": 0.1951219512195122, "avoid": 0.26829268292682923}, "informative": false}]
Reward-accepted indices: [3]
World-specific reward sets: {"want": [3], "neutral": [3], "avoid": [1]}

## 17. interaction-3c27c1da593c0872c6
single_ambiguous / repair_sensitive; goals=3; parent=v7-natural-760238

Gold: {"possible_preferences": ["want", "neutral", "avoid"], "favored": "undetermined"}
Evidence: [{"actor": 1, "event": {"action": "OFFER", "partner_id": 0, "proposer_action": [0, 0], "partner_action": [1, 0]}, "before": {"want": 0.3333333333333333, "neutral": 0.3333333333333333, "avoid": 0.3333333333333333}, "after": {"want": 0.45, "neutral": 0.45, "avoid": 0.1}, "informative": true}, {"actor": 0, "event": {"response": "ACCEPT"}, "before": {"want": 0.45, "neutral": 0.45, "avoid": 0.1}, "after": {"want": 0.45, "neutral": 0.45, "avoid": 0.1}, "informative": false}]
Reward-accepted indices: [4]
World-specific reward sets: {"want": [4], "neutral": [4], "avoid": [3]}

## 18. interaction-5f842a0d9edc689e57
single_ambiguous / repair_sensitive; goals=3; parent=v7-natural-760158

Gold: {"possible_preferences": ["want", "neutral", "avoid"], "favored": "undetermined"}
Evidence: [{"actor": 1, "event": {"action": "OFFER", "partner_id": 0, "proposer_action": [0, 0], "partner_action": [1, 0]}, "before": {"want": 0.3333333333333333, "neutral": 0.3333333333333333, "avoid": 0.3333333333333333}, "after": {"want": 0.45, "neutral": 0.45, "avoid": 0.1}, "informative": true}, {"actor": 0, "event": {"response": "ACCEPT"}, "before": {"want": 0.45, "neutral": 0.45, "avoid": 0.1}, "after": {"want": 0.45, "neutral": 0.45, "avoid": 0.1}, "informative": false}]
Reward-accepted indices: [5]
World-specific reward sets: {"want": [5], "neutral": [5], "avoid": [3]}

## 19. layer-4457d01e9a4d1a29bb
multi_update / action_control; goals=3; parent=8f243ad7ea27aaa2dcc9cdba27299363e9f5c3a35382e6b3ab7dcc2c07120251-v8-window

Gold: {"possible_preferences": ["avoid"], "favored": "avoid"}
Evidence: [{"actor": 1, "event": {"action": "OFFER", "partner_id": 0, "proposer_action": [0, 0], "partner_action": [1, 0]}, "before": {"want": 0.5, "neutral": 0.25, "avoid": 0.25}, "after": {"want": 0.5625, "neutral": 0.28125, "avoid": 0.15625}, "informative": true}, {"actor": 0, "event": {"response": "ACCEPT"}, "before": {"want": 0.5625, "neutral": 0.28125, "avoid": 0.15625}, "after": {"want": 0.5625, "neutral": 0.28125, "avoid": 0.15625}, "informative": false}, {"actor": 1, "event": {"action": "OFFER", "partner_id": 0, "proposer_action": [0, 0], "partner_action": [1, 1]}, "before": {"want": 0.5625, "neutral": 0.28125, "avoid": 0.15625}, "after": {"want": 0.0, "neutral": 0.0, "avoid": 1.0}, "informative": true}]
Reward-accepted indices: [0, 1]
World-specific reward sets: {"want": [0, 1], "neutral": [0, 1], "avoid": [0, 1]}

## 20. layer-73f4c4e5cd288bc424
multi_update / action_control; goals=3; parent=8771786eeda211936d17f8f0605441d136e574a5a7fe0f295e75cad5a15b7b5b-v8-window

Gold: {"possible_preferences": ["neutral", "avoid"], "favored": "avoid"}
Evidence: [{"actor": 1, "event": {"action": "PASS"}, "before": {"want": 0.25, "neutral": 0.5, "avoid": 0.25}, "after": {"want": 0.2222222222222222, "neutral": 0.4444444444444444, "avoid": 0.3333333333333333}, "informative": true}, {"actor": 1, "event": {"action": "OFFER", "partner_id": 0, "proposer_action": [0, 0], "partner_action": [1, 0]}, "before": {"want": 0.2222222222222222, "neutral": 0.4444444444444444, "avoid": 0.3333333333333333}, "after": {"want": 0.0, "neutral": 0.4, "avoid": 0.6}, "informative": true}]
Reward-accepted indices: [1]
World-specific reward sets: {"want": [1], "neutral": [1], "avoid": [1]}

## 21. layer-5e387f55124014433a
multi_update / action_control; goals=3; parent=1ff5580a85eddc054a1e3367eb23b5cd8a74da070c49d731eb34369081ab24d4-v8-window

Gold: {"possible_preferences": ["avoid"], "favored": "avoid"}
Evidence: [{"actor": 1, "event": {"action": "OFFER", "partner_id": 0, "proposer_action": [0, 0], "partner_action": [1, 0]}, "before": {"want": 0.25, "neutral": 0.5, "avoid": 0.25}, "after": {"want": 0.28125, "neutral": 0.5625, "avoid": 0.15625}, "informative": true}, {"actor": 0, "event": {"response": "ACCEPT"}, "before": {"want": 0.28125, "neutral": 0.5625, "avoid": 0.15625}, "after": {"want": 0.28125, "neutral": 0.5625, "avoid": 0.15625}, "informative": false}, {"actor": 1, "event": {"action": "OFFER", "partner_id": 0, "proposer_action": [0, 0], "partner_action": [1, 1]}, "before": {"want": 0.28125, "neutral": 0.5625, "avoid": 0.15625}, "after": {"want": 0.0, "neutral": 0.0, "avoid": 1.0}, "informative": true}]
Reward-accepted indices: [0, 1]
World-specific reward sets: {"want": [0, 1], "neutral": [0, 1], "avoid": [0, 1]}

## 22. layer-d4f4781fe5977e7e36
multi_update / action_control; goals=3; parent=77a6bb7005e27424188fca4aa2a1ac9ec75e7d7acedca898a90df44c85423d17-v8-window

Gold: {"possible_preferences": ["avoid"], "favored": "avoid"}
Evidence: [{"actor": 1, "event": {"action": "OFFER", "partner_id": 0, "proposer_action": [0, 0], "partner_action": [1, 0]}, "before": {"want": 0.3333333333333333, "neutral": 0.3333333333333333, "avoid": 0.3333333333333333}, "after": {"want": 0.391304347826087, "neutral": 0.391304347826087, "avoid": 0.21739130434782608}, "informative": true}, {"actor": 0, "event": {"response": "ACCEPT"}, "before": {"want": 0.391304347826087, "neutral": 0.391304347826087, "avoid": 0.21739130434782608}, "after": {"want": 0.391304347826087, "neutral": 0.391304347826087, "avoid": 0.21739130434782608}, "informative": false}, {"actor": 1, "event": {"action": "OFFER", "partner_id": 0, "proposer_action": [0, 0], "partner_action": [1, 1]}, "before": {"want": 0.391304347826087, "neutral": 0.391304347826087, "avoid": 0.21739130434782608}, "after": {"want": 0.0, "neutral": 0.0, "avoid": 1.0}, "informative": true}]
Reward-accepted indices: [0, 1]
World-specific reward sets: {"want": [0, 1], "neutral": [0, 1], "avoid": [0, 1]}

