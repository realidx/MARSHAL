# Self-play prompt v4：待审阅

这是当前代码展开的新版题面，不是旧模型请求的原样摘录。尚未调用模型。每个样例包含完整 system、user 和 tools；不展示教师标签、隐藏世界或模型答案。

## 本次修改依据

- 参考 MARSHAL 原有 `roll/agentic/env/kuhn_poker/env.py`、`leduc_poker/env.py`、`hanabi/env.py` 的 `_get_prefix_prompt`：system 说明目标，user 分开提供规则、玩家信息和作答要求。
- ALL_OF 游戏直接使用 `training/b_sft/social_prompt.py` 的五条 GAME RULES，逐字一致。LINEAR／混合游戏仅按当前环境替换第 1、2 条；第 3–5 条一致。
- 移除 system 中的协议扣分、重试和网络故障说明。作答要求为先解释决策，再调用一个原生工具；解释仅自己可见，放在工具参数外，不限制句数。
- 玩家仍以自身终局收益为目标。当前环境中的 LINEAR 计分、内部扣分和重试机制没有在这次题面修改中调整。

## ALL_OF 游戏：提案阶段

现有开局库 `interacting_commitments_a-r2-s0`；从零承诺的实际开局展开。

### System message

```text
You are a player in a negotiation game with binding commitments. Your objective is to maximize your own expected final score.
```

### User message

```text
GAME RULES
1. Goals and commitments: A goal is achieved when ALL its listed player-specific commitments are binding. A player's preference does not change this condition. One binding commitment can contribute to several goals without completing all of them.
2. Payoffs: At the end of the game, each achieved goal gives each player +1 for want, 0 for neutral, or -1 for avoid. An unachieved goal gives everyone 0. Each player's final score is the sum of their scores from all goals.
3. Offers: OFFER proposes NEW commitments for the proposer and partner. These are commitments each player will undertake, not items transferred between players. ACCEPT binds all proposed additions; REJECT binds none. Existing binding commitments cannot be removed.
4. Timing: A proposal and its response together use one proposal opportunity. PASS uses that opportunity without adding commitments. Players follow the remaining proposal order shown below. The game ends after the final opportunity, including its response if an offer was made.
5. Investigation: Each player can investigate once per game. INVESTIGATE spends the current proposal opportunity and that use. Choose any other player and any goal. The environment reveals that player's true preference for the goal only to the investigator. Everyone sees who investigated whom about which goal. Each player knows their own preferences.

PLAYER INFORMATION
You are Alex.
Each player's objective is to maximize their own expected final score. Their preferences may differ from yours.
You observe the public game history, your own preferences, and investigation answers delivered to you. Other players observe their own preferences and their own investigation answers.

GOALS AND COMMITMENTS
- Orchard (BINARY: all required): Alex to commit to Cedar; Blair to commit to Maple. Currently 0 of 2 requirements are binding; completion=0.
- Harbor (BINARY: all required): Alex to commit to Maple; Blair to commit to Cedar. Currently 0 of 2 requirements are binding; completion=0.
- Library (BINARY: all required): Alex to commit to Cedar; Blair to commit to Cedar. Currently 0 of 2 requirements are binding; completion=0.
Already binding (currently in force):
- Alex: none.
- Blair: none.
Commitment options still available to add (not yet binding):
- Alex: Cedar, Maple.
- Blair: Cedar, Maple.
An offer may add at most 1 new commitment(s) per involved player.

WHAT YOU KNOW
- You want Orchard.
- You want Harbor.
- You want Library.
Other preferences not directly revealed to you: Blair's preference for Orchard, Blair's preference for Harbor, Blair's preference for Library.

HOW PREFERENCES ARE DRAWN
Initially, every player-goal preference is drawn independently with equal chances of want, neutral and avoid. Draws are repeated until each player wants at least one goal and each goal has at least one player who is not neutral about it. Everyone knows these rules; there are no other restrictions on preferences. Preferences stay fixed throughout the game.

HISTORY VISIBLE TO EVERYONE
No earlier events.

CURRENT DECISION
Remaining proposal order (first entry is the current opportunity, including its response): Alex -> Blair -> Alex -> Blair.
Your proposal opportunities AFTER the current opportunity: 1.
Investigation uses remaining: Alex=1; Blair=1.
Make your proposal decision now.

RESPONSE INSTRUCTIONS
Briefly explain your decision based on the current game state and the information available to you, then make exactly one game-action tool call. Your explanation is private and is not shown to other players. Keep it outside the tool arguments.
Choose one of the legal actions defined by the registered tools and their allowed argument combinations.
Call the chosen action tool directly. OFFER takes partner, self_commitments and partner_commitments; INVESTIGATE takes player and goal; PASS, ACCEPT and REJECT take no arguments. The registered tools list the legal choices.
```

### Tools（完整 schema）

```json
[
  {
    "type": "function",
    "function": {
      "name": "PASS",
      "description": "Spend the current proposal opportunity without adding commitments.",
      "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": false,
        "enum": [
          {}
        ]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "OFFER",
      "description": "Propose NEW commitments for yourself and your partner. Acceptance binds both sets of additions.",
      "parameters": {
        "type": "object",
        "properties": {
          "partner": {
            "type": "string",
            "enum": [
              "Blair"
            ]
          },
          "self_commitments": {
            "type": "array",
            "items": {
              "type": "string",
              "enum": [
                "Cedar",
                "Maple"
              ]
            },
            "uniqueItems": true,
            "maxItems": 1,
            "description": "Your own NEW commitments."
          },
          "partner_commitments": {
            "type": "array",
            "items": {
              "type": "string",
              "enum": [
                "Cedar",
                "Maple"
              ]
            },
            "uniqueItems": true,
            "maxItems": 1,
            "description": "Your partner's NEW commitments."
          }
        },
        "required": [
          "partner",
          "self_commitments",
          "partner_commitments"
        ],
        "additionalProperties": false,
        "enum": [
          {
            "partner": "Blair",
            "self_commitments": [],
            "partner_commitments": [
              "Cedar"
            ]
          },
          {
            "partner": "Blair",
            "self_commitments": [],
            "partner_commitments": [
              "Maple"
            ]
          },
          {
            "partner": "Blair",
            "self_commitments": [
              "Cedar"
            ],
            "partner_commitments": []
          },
          {
            "partner": "Blair",
            "self_commitments": [
              "Cedar"
            ],
            "partner_commitments": [
              "Cedar"
            ]
          },
          {
            "partner": "Blair",
            "self_commitments": [
              "Cedar"
            ],
            "partner_commitments": [
              "Maple"
            ]
          },
          {
            "partner": "Blair",
            "self_commitments": [
              "Maple"
            ],
            "partner_commitments": []
          },
          {
            "partner": "Blair",
            "self_commitments": [
              "Maple"
            ],
            "partner_commitments": [
              "Cedar"
            ]
          },
          {
            "partner": "Blair",
            "self_commitments": [
              "Maple"
            ],
            "partner_commitments": [
              "Maple"
            ]
          }
        ]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "INVESTIGATE",
      "description": "Spend the current proposal opportunity and your investigation use to privately learn the selected player's true preference for the selected goal.",
      "parameters": {
        "type": "object",
        "properties": {
          "player": {
            "type": "string",
            "enum": [
              "Blair"
            ]
          },
          "goal": {
            "type": "string",
            "enum": [
              "Harbor",
              "Library",
              "Orchard"
            ]
          }
        },
        "required": [
          "player",
          "goal"
        ],
        "additionalProperties": false,
        "enum": [
          {
            "player": "Blair",
            "goal": "Orchard"
          },
          {
            "player": "Blair",
            "goal": "Harbor"
          },
          {
            "player": "Blair",
            "goal": "Library"
          }
        ]
      }
    }
  }
]
```

## LINEAR 游戏：提案阶段

复用作业 846757 的可见状态：`runs/outcome_selfplay_screen/reviews/nus-846757.3fYhvS/rollout/group-0-rollout-0.calls.jsonl` 第 1 行；使用新版 prompt 重新展开，尚未发送模型。

### System message

```text
You are a player in a negotiation game with binding commitments. Your objective is to maximize your own expected final score.
```

### User message

```text
GAME RULES
1. Goals and commitments: Each goal lists player-specific commitments. A goal's completion is the fraction of its listed commitments that are binding. A player's preference does not change this condition. One binding commitment can contribute to several goals.
2. Payoffs: At the end of the game, each goal gives each player its completion multiplied by +1 for want, 0 for neutral, or -1 for avoid. A goal with completion 0 gives everyone 0. Each player's final score is the sum of their scores from all goals.
3. Offers: OFFER proposes NEW commitments for the proposer and partner. These are commitments each player will undertake, not items transferred between players. ACCEPT binds all proposed additions; REJECT binds none. Existing binding commitments cannot be removed.
4. Timing: A proposal and its response together use one proposal opportunity. PASS uses that opportunity without adding commitments. Players follow the remaining proposal order shown below. The game ends after the final opportunity, including its response if an offer was made.
5. Investigation: Each player can investigate once per game. INVESTIGATE spends the current proposal opportunity and that use. Choose any other player and any goal. The environment reveals that player's true preference for the goal only to the investigator. Everyone sees who investigated whom about which goal. Each player knows their own preferences.

PLAYER INFORMATION
You are Blair.
Each player's objective is to maximize their own expected final score. Their preferences may differ from yours.
You observe the public game history, your own preferences, and investigation answers delivered to you. Other players observe their own preferences and their own investigation answers.

GOALS AND COMMITMENTS
- Orchard (LINEAR: fraction of requirements): Alex to commit to Cedar; Blair to commit to Cedar. Currently 0 of 2 requirements are binding; completion=0.
- Harbor (LINEAR: fraction of requirements): Alex to commit to Maple; Blair to commit to Cedar. Currently 0 of 2 requirements are binding; completion=0.
Already binding (currently in force):
- Alex: none.
- Blair: none.
Commitment options still available to add (not yet binding):
- Alex: Cedar, Maple.
- Blair: Cedar.
An offer may add at most 1 new commitment(s) per involved player.

WHAT YOU KNOW
- You want Orchard.
- You are neutral about Harbor.
Other preferences not directly revealed to you: Alex's preference for Orchard, Alex's preference for Harbor.

HOW PREFERENCES ARE DRAWN
Initially, every player-goal preference is drawn independently with equal chances of want and neutral. Draws are repeated until each player wants at least one goal and each goal has at least one player who is not neutral about it. Everyone knows these rules; there are no other restrictions on preferences. Preferences stay fixed throughout the game.

HISTORY VISIBLE TO EVERYONE
No earlier events.

CURRENT DECISION
Remaining proposal order (first entry is the current opportunity, including its response): Blair -> Alex -> Alex -> Blair.
Your proposal opportunities AFTER the current opportunity: 1.
Investigation uses remaining: Alex=1; Blair=1.
Make your proposal decision now.

RESPONSE INSTRUCTIONS
Briefly explain your decision based on the current game state and the information available to you, then make exactly one game-action tool call. Your explanation is private and is not shown to other players. Keep it outside the tool arguments.
Choose one of the legal actions defined by the registered tools and their allowed argument combinations.
Call the chosen action tool directly. OFFER takes partner, self_commitments and partner_commitments; INVESTIGATE takes player and goal; PASS, ACCEPT and REJECT take no arguments. The registered tools list the legal choices.
```

### Tools（完整 schema）

```json
[
  {
    "type": "function",
    "function": {
      "name": "PASS",
      "description": "Spend the current proposal opportunity without adding commitments.",
      "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": false,
        "enum": [
          {}
        ]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "OFFER",
      "description": "Propose NEW commitments for yourself and your partner. Acceptance binds both sets of additions.",
      "parameters": {
        "type": "object",
        "properties": {
          "partner": {
            "type": "string",
            "enum": [
              "Alex"
            ]
          },
          "self_commitments": {
            "type": "array",
            "items": {
              "type": "string",
              "enum": [
                "Cedar"
              ]
            },
            "uniqueItems": true,
            "maxItems": 1,
            "description": "Your own NEW commitments."
          },
          "partner_commitments": {
            "type": "array",
            "items": {
              "type": "string",
              "enum": [
                "Cedar",
                "Maple"
              ]
            },
            "uniqueItems": true,
            "maxItems": 1,
            "description": "Your partner's NEW commitments."
          }
        },
        "required": [
          "partner",
          "self_commitments",
          "partner_commitments"
        ],
        "additionalProperties": false,
        "enum": [
          {
            "partner": "Alex",
            "self_commitments": [],
            "partner_commitments": [
              "Cedar"
            ]
          },
          {
            "partner": "Alex",
            "self_commitments": [],
            "partner_commitments": [
              "Maple"
            ]
          },
          {
            "partner": "Alex",
            "self_commitments": [
              "Cedar"
            ],
            "partner_commitments": []
          },
          {
            "partner": "Alex",
            "self_commitments": [
              "Cedar"
            ],
            "partner_commitments": [
              "Cedar"
            ]
          },
          {
            "partner": "Alex",
            "self_commitments": [
              "Cedar"
            ],
            "partner_commitments": [
              "Maple"
            ]
          }
        ]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "INVESTIGATE",
      "description": "Spend the current proposal opportunity and your investigation use to privately learn the selected player's true preference for the selected goal.",
      "parameters": {
        "type": "object",
        "properties": {
          "player": {
            "type": "string",
            "enum": [
              "Alex"
            ]
          },
          "goal": {
            "type": "string",
            "enum": [
              "Harbor",
              "Orchard"
            ]
          }
        },
        "required": [
          "player",
          "goal"
        ],
        "additionalProperties": false,
        "enum": [
          {
            "player": "Alex",
            "goal": "Orchard"
          },
          {
            "player": "Alex",
            "goal": "Harbor"
          }
        ]
      }
    }
  }
]
```

## 响应阶段

复用作业 846757 的可见状态：`runs/outcome_selfplay_screen/reviews/nus-846757.3fYhvS/rollout/group-0-rollout-0.calls.jsonl` 第 4 行；使用新版 prompt 重新展开，尚未发送模型。

### System message

```text
You are a player in a negotiation game with binding commitments. Your objective is to maximize your own expected final score.
```

### User message

```text
GAME RULES
1. Goals and commitments: Each goal lists player-specific commitments. A goal's completion is the fraction of its listed commitments that are binding. A player's preference does not change this condition. One binding commitment can contribute to several goals.
2. Payoffs: At the end of the game, each goal gives each player its completion multiplied by +1 for want, 0 for neutral, or -1 for avoid. A goal with completion 0 gives everyone 0. Each player's final score is the sum of their scores from all goals.
3. Offers: OFFER proposes NEW commitments for the proposer and partner. These are commitments each player will undertake, not items transferred between players. ACCEPT binds all proposed additions; REJECT binds none. Existing binding commitments cannot be removed.
4. Timing: A proposal and its response together use one proposal opportunity. PASS uses that opportunity without adding commitments. Players follow the remaining proposal order shown below. The game ends after the final opportunity, including its response if an offer was made.
5. Investigation: Each player can investigate once per game. INVESTIGATE spends the current proposal opportunity and that use. Choose any other player and any goal. The environment reveals that player's true preference for the goal only to the investigator. Everyone sees who investigated whom about which goal. Each player knows their own preferences.

PLAYER INFORMATION
You are Blair.
Each player's objective is to maximize their own expected final score. Their preferences may differ from yours.
You observe the public game history, your own preferences, and investigation answers delivered to you. Other players observe their own preferences and their own investigation answers.

GOALS AND COMMITMENTS
- Orchard (LINEAR: fraction of requirements): Alex to commit to Cedar; Blair to commit to Cedar. Currently 0 of 2 requirements are binding; completion=0.
- Harbor (LINEAR: fraction of requirements): Alex to commit to Maple; Blair to commit to Cedar. Currently 0 of 2 requirements are binding; completion=0.
Already binding (currently in force):
- Alex: none.
- Blair: none.
Commitment options still available to add (not yet binding):
- Alex: Cedar, Maple.
- Blair: Cedar.
An offer may add at most 1 new commitment(s) per involved player.

WHAT YOU KNOW
- You want Orchard.
- You are neutral about Harbor.
- Your investigation revealed that Alex is neutral about Orchard. The answer was shown only to you.
Other preferences not directly revealed to you: Alex's preference for Harbor.

HOW PREFERENCES ARE DRAWN
Initially, every player-goal preference is drawn independently with equal chances of want and neutral. Draws are repeated until each player wants at least one goal and each goal has at least one player who is not neutral about it. Everyone knows these rules; there are no other restrictions on preferences. Preferences stay fixed throughout the game.

HISTORY VISIBLE TO EVERYONE
1. Blair chose to investigate Alex's preference for Orchard. The answer is delivered privately to Blair, not broadcast. No commitments are added.
2. Alex chose to investigate Blair's preference for Harbor. The answer is delivered privately to Alex, not broadcast. No commitments are added.
3. Alex chose to propose to Blair: Alex would add Maple; Blair would add Cedar. This proposal alone binds nothing.

CURRENT DECISION
Remaining proposal order (first entry is the current opportunity, including its response): Alex -> Blair.
Your proposal opportunities AFTER the current opportunity: 1.
Investigation uses remaining: Alex=0; Blair=0.
Pending offer from Alex to Blair: Alex would add Maple; Blair would add Cedar. These additions are not yet binding.
Respond to this pending offer now.

RESPONSE INSTRUCTIONS
Briefly explain your decision based on the current game state and the information available to you, then make exactly one game-action tool call. Your explanation is private and is not shown to other players. Keep it outside the tool arguments.
Choose one of the legal actions defined by the registered tools and their allowed argument combinations.
Call the chosen action tool directly. OFFER takes partner, self_commitments and partner_commitments; INVESTIGATE takes player and goal; PASS, ACCEPT and REJECT take no arguments. The registered tools list the legal choices.
```

### Tools（完整 schema）

```json
[
  {
    "type": "function",
    "function": {
      "name": "REJECT",
      "description": "Reject the pending offer without binding its additions.",
      "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": false,
        "enum": [
          {}
        ]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "ACCEPT",
      "description": "Accept the pending offer and bind its additions.",
      "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": false,
        "enum": [
          {}
        ]
      }
    }
  }
]
```

## 取得私有调查结果后的提案阶段

复用作业 846757 的可见状态：`runs/outcome_selfplay_screen/reviews/nus-846757.3fYhvS/rollout/group-0-rollout-0.calls.jsonl` 第 3 行；使用新版 prompt 重新展开，尚未发送模型。

### System message

```text
You are a player in a negotiation game with binding commitments. Your objective is to maximize your own expected final score.
```

### User message

```text
GAME RULES
1. Goals and commitments: Each goal lists player-specific commitments. A goal's completion is the fraction of its listed commitments that are binding. A player's preference does not change this condition. One binding commitment can contribute to several goals.
2. Payoffs: At the end of the game, each goal gives each player its completion multiplied by +1 for want, 0 for neutral, or -1 for avoid. A goal with completion 0 gives everyone 0. Each player's final score is the sum of their scores from all goals.
3. Offers: OFFER proposes NEW commitments for the proposer and partner. These are commitments each player will undertake, not items transferred between players. ACCEPT binds all proposed additions; REJECT binds none. Existing binding commitments cannot be removed.
4. Timing: A proposal and its response together use one proposal opportunity. PASS uses that opportunity without adding commitments. Players follow the remaining proposal order shown below. The game ends after the final opportunity, including its response if an offer was made.
5. Investigation: Each player can investigate once per game. INVESTIGATE spends the current proposal opportunity and that use. Choose any other player and any goal. The environment reveals that player's true preference for the goal only to the investigator. Everyone sees who investigated whom about which goal. Each player knows their own preferences.

PLAYER INFORMATION
You are Alex.
Each player's objective is to maximize their own expected final score. Their preferences may differ from yours.
You observe the public game history, your own preferences, and investigation answers delivered to you. Other players observe their own preferences and their own investigation answers.

GOALS AND COMMITMENTS
- Orchard (LINEAR: fraction of requirements): Alex to commit to Cedar; Blair to commit to Cedar. Currently 0 of 2 requirements are binding; completion=0.
- Harbor (LINEAR: fraction of requirements): Alex to commit to Maple; Blair to commit to Cedar. Currently 0 of 2 requirements are binding; completion=0.
Already binding (currently in force):
- Alex: none.
- Blair: none.
Commitment options still available to add (not yet binding):
- Alex: Cedar, Maple.
- Blair: Cedar.
An offer may add at most 1 new commitment(s) per involved player.

WHAT YOU KNOW
- You are neutral about Orchard.
- You want Harbor.
- Your investigation revealed that Blair is neutral about Harbor. The answer was shown only to you.
Other preferences not directly revealed to you: Blair's preference for Orchard.

HOW PREFERENCES ARE DRAWN
Initially, every player-goal preference is drawn independently with equal chances of want and neutral. Draws are repeated until each player wants at least one goal and each goal has at least one player who is not neutral about it. Everyone knows these rules; there are no other restrictions on preferences. Preferences stay fixed throughout the game.

HISTORY VISIBLE TO EVERYONE
1. Blair chose to investigate Alex's preference for Orchard. The answer is delivered privately to Blair, not broadcast. No commitments are added.
2. Alex chose to investigate Blair's preference for Harbor. The answer is delivered privately to Alex, not broadcast. No commitments are added.

CURRENT DECISION
Remaining proposal order (first entry is the current opportunity, including its response): Alex -> Blair.
Your proposal opportunities AFTER the current opportunity: 0.
Investigation uses remaining: Alex=0; Blair=0.
Make your proposal decision now.

RESPONSE INSTRUCTIONS
Briefly explain your decision based on the current game state and the information available to you, then make exactly one game-action tool call. Your explanation is private and is not shown to other players. Keep it outside the tool arguments.
Choose one of the legal actions defined by the registered tools and their allowed argument combinations.
Call the chosen action tool directly. OFFER takes partner, self_commitments and partner_commitments; INVESTIGATE takes player and goal; PASS, ACCEPT and REJECT take no arguments. The registered tools list the legal choices.
```

### Tools（完整 schema）

```json
[
  {
    "type": "function",
    "function": {
      "name": "PASS",
      "description": "Spend the current proposal opportunity without adding commitments.",
      "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": false,
        "enum": [
          {}
        ]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "OFFER",
      "description": "Propose NEW commitments for yourself and your partner. Acceptance binds both sets of additions.",
      "parameters": {
        "type": "object",
        "properties": {
          "partner": {
            "type": "string",
            "enum": [
              "Blair"
            ]
          },
          "self_commitments": {
            "type": "array",
            "items": {
              "type": "string",
              "enum": [
                "Cedar",
                "Maple"
              ]
            },
            "uniqueItems": true,
            "maxItems": 1,
            "description": "Your own NEW commitments."
          },
          "partner_commitments": {
            "type": "array",
            "items": {
              "type": "string",
              "enum": [
                "Cedar"
              ]
            },
            "uniqueItems": true,
            "maxItems": 1,
            "description": "Your partner's NEW commitments."
          }
        },
        "required": [
          "partner",
          "self_commitments",
          "partner_commitments"
        ],
        "additionalProperties": false,
        "enum": [
          {
            "partner": "Blair",
            "self_commitments": [],
            "partner_commitments": [
              "Cedar"
            ]
          },
          {
            "partner": "Blair",
            "self_commitments": [
              "Cedar"
            ],
            "partner_commitments": []
          },
          {
            "partner": "Blair",
            "self_commitments": [
              "Cedar"
            ],
            "partner_commitments": [
              "Cedar"
            ]
          },
          {
            "partner": "Blair",
            "self_commitments": [
              "Maple"
            ],
            "partner_commitments": []
          },
          {
            "partner": "Blair",
            "self_commitments": [
              "Maple"
            ],
            "partner_commitments": [
              "Cedar"
            ]
          }
        ]
      }
    }
  }
]
```

## 仅在无效提交后发送的纠正提示

该提示不在首次请求中，也没有扣分或服务器说明。

```text
Your response did not complete one valid game-action tool call. The game state is unchanged. Make one actual call to a registered action tool using one of its allowed argument combinations. OFFER lists only NEW named commitments; PASS, ACCEPT and REJECT take no arguments.
```
