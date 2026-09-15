# B response bridges: visible prompts and separate checks

## Lesson level 0: e4e9396536f45f0de445

GAME RULES
1. Goals and commitments: A goal is achieved when ALL its listed player-specific commitments are binding. A player's preference does not change this condition. One binding commitment can contribute to several goals without completing all of them.
2. Payoffs: At the end of the game, each achieved goal gives each player +1 for want, 0 for neutral, or -1 for avoid. An unachieved goal gives everyone 0. Each player's final score is the sum of their scores from all goals.
3. Offers: OFFER proposes NEW commitments for the proposer and partner. These are commitments each player will undertake, not items transferred between players. ACCEPT binds all proposed additions; REJECT binds none. Existing binding commitments cannot be removed.
4. Timing: A proposal and its response together use one proposal opportunity. PASS uses that opportunity without adding commitments. Players follow the remaining proposal order shown below. The game ends after the final opportunity, including its response if an offer was made.
5. Investigation: Each player can investigate once per game. INVESTIGATE spends the current proposal opportunity and that use. Choose any other player and any goal. The environment reveals that player's true preference for the goal only to the investigator. Everyone sees who investigated whom about which goal. Each player knows their own preferences.

YOUR ROLE AND TASK
You are Blair.
Assess the requested belief; do not take a game action.

GOALS AND COMMITMENTS
- Harbor requires Blair to commit to Maple and Alex to commit to Maple.
- Orchard requires Blair to commit to Willow and Alex to commit to Maple.
Already binding (currently in force):
- Blair: Maple.
- Alex: Maple.
Commitment options still available to add (not yet binding):
- Blair: Willow.
- Alex: none.
An offer may add at most 1 new commitment(s) per involved player.

WHAT YOU KNOW
- You are neutral about Harbor. Everyone knows this preference.
- You want Orchard. Everyone knows this preference.
- Alex wants Orchard. Everyone knows this preference.
Correct PREVIOUS belief about Alex / Harbor (before the new evidence): possible_preferences=["want", "avoid"], favored=undetermined.

HOW PREFERENCES ARE DRAWN
The preferences known to everyone are fixed. Initially, each other preference is drawn independently with equal chances of want, neutral and avoid. Draws are repeated until each player wants at least one goal and each goal has at least one player who is not neutral about it. Everyone knows these rules; there are no other restrictions on preferences.

HOW OTHER PLAYERS CHOOSE
Other players plan for the end of the game using the actions everyone has seen, their own preferences and their own investigation answers. They choose actions that maximize their expected final score. On a tie, they prefer the highest total expected score for the other players. If actions still tie, they choose equally at random among them.

HISTORY VISIBLE TO EVERYONE
Starting events were provided by the task, independently of preferences, rather than chosen by players. They do not reveal what a player prefers.
1. [earlier history] Starting event provided by the task: Alex passes. No commitments are added.
2. [earlier history] Starting event provided by the task: Blair proposes to Alex: Blair would add Maple; Alex would add Maple. This proposal alone binds nothing.
3. [new evidence] Alex chose to accept Blair's offer. New binding commitments: Blair: Maple; Alex: Maple.

CURRENT DECISION
No proposal opportunities remain; the game history is complete.
Investigation uses remaining: Blair=1; Alex=1.
Assess ONLY Alex's preference for Harbor.
possible_preferences is the set of values STILL compatible with the available evidence, not a list of all preference words. A true revealed value leaves only that value. favored is the uniquely most supported remaining value, even when other values remain possible; use undetermined if the top support is tied. Undetermined does not mean all values are equally supported. Keep all three values when all three remain compatible; exclude a value only with a valid reason. Compare the observed choices with what each candidate preference would lead the player to do. When a correct previous belief is supplied, carry it forward and apply the new evidence. Your answer must match the conclusion in your explanation.
Submit one SUBMIT_BELIEFS call. Its arguments contain judgments: a one-element list of objects with player, goal, possible_preferences (a list), and favored. Do not take a game action.

### Local teacher check (never sent to learner)

```json
{
  "gold": {
    "possible_preferences": [
      "want"
    ],
    "favored": "want"
  },
  "completed_goals": {
    "ACCEPT": [
      true,
      false
    ],
    "REJECT": [
      false,
      false
    ]
  },
  "world_checks": [
    {
      "preference": "want",
      "responder_preferences": [
        1,
        1
      ],
      "payoffs": {
        "ACCEPT": [
          0,
          1
        ],
        "REJECT": [
          0,
          0
        ]
      },
      "response_likelihood": {
        "ACCEPT": "1",
        "REJECT": "0"
      }
    },
    {
      "preference": "avoid",
      "responder_preferences": [
        -1,
        1
      ],
      "payoffs": {
        "ACCEPT": [
          0,
          -1
        ],
        "REJECT": [
          0,
          0
        ]
      },
      "response_likelihood": {
        "ACCEPT": "0",
        "REJECT": "1"
      }
    }
  ],
  "posterior": {
    "want": "1",
    "neutral": "0",
    "avoid": "0"
  },
  "scope": "Exact final-response check; responder knows every fact used in their payoff comparison."
}
```

## Lesson level 1: 8a1552eb5361c3f680de

GAME RULES
1. Goals and commitments: A goal is achieved when ALL its listed player-specific commitments are binding. A player's preference does not change this condition. One binding commitment can contribute to several goals without completing all of them.
2. Payoffs: At the end of the game, each achieved goal gives each player +1 for want, 0 for neutral, or -1 for avoid. An unachieved goal gives everyone 0. Each player's final score is the sum of their scores from all goals.
3. Offers: OFFER proposes NEW commitments for the proposer and partner. These are commitments each player will undertake, not items transferred between players. ACCEPT binds all proposed additions; REJECT binds none. Existing binding commitments cannot be removed.
4. Timing: A proposal and its response together use one proposal opportunity. PASS uses that opportunity without adding commitments. Players follow the remaining proposal order shown below. The game ends after the final opportunity, including its response if an offer was made.
5. Investigation: Each player can investigate once per game. INVESTIGATE spends the current proposal opportunity and that use. Choose any other player and any goal. The environment reveals that player's true preference for the goal only to the investigator. Everyone sees who investigated whom about which goal. Each player knows their own preferences.

YOUR ROLE AND TASK
You are Blair.
Assess the requested belief; do not take a game action.

GOALS AND COMMITMENTS
- Harbor requires Blair to commit to Maple and Alex to commit to Maple.
- Orchard requires Blair to commit to Willow and Alex to commit to Maple.
Already binding (currently in force):
- Blair: Maple.
- Alex: Maple.
Commitment options still available to add (not yet binding):
- Blair: Willow.
- Alex: none.
An offer may add at most 1 new commitment(s) per involved player.

WHAT YOU KNOW
- You want Harbor. Everyone knows this preference.
- You want Orchard. Everyone knows this preference.
- Alex wants Orchard. Everyone knows this preference.
Correct PREVIOUS belief about Alex / Harbor (before the new evidence): possible_preferences=["want", "neutral", "avoid"], favored=undetermined.

HOW PREFERENCES ARE DRAWN
The preferences known to everyone are fixed. Initially, each other preference is drawn independently with equal chances of want, neutral and avoid. Draws are repeated until each player wants at least one goal and each goal has at least one player who is not neutral about it. Everyone knows these rules; there are no other restrictions on preferences.

HOW OTHER PLAYERS CHOOSE
Other players plan for the end of the game using the actions everyone has seen, their own preferences and their own investigation answers. They choose actions that maximize their expected final score. On a tie, they prefer the highest total expected score for the other players. If actions still tie, they choose equally at random among them.

HISTORY VISIBLE TO EVERYONE
Starting events were provided by the task, independently of preferences, rather than chosen by players. They do not reveal what a player prefers.
1. [earlier history] Starting event provided by the task: Alex passes. No commitments are added.
2. [earlier history] Starting event provided by the task: Blair proposes to Alex: Blair would add Maple; Alex would add Maple. This proposal alone binds nothing.
3. [new evidence] Alex chose to accept Blair's offer. New binding commitments: Blair: Maple; Alex: Maple.

CURRENT DECISION
No proposal opportunities remain; the game history is complete.
Investigation uses remaining: Blair=1; Alex=1.
Assess ONLY Alex's preference for Harbor.
possible_preferences is the set of values STILL compatible with the available evidence, not a list of all preference words. A true revealed value leaves only that value. favored is the uniquely most supported remaining value, even when other values remain possible; use undetermined if the top support is tied. Undetermined does not mean all values are equally supported. Keep all three values when all three remain compatible; exclude a value only with a valid reason. Compare the observed choices with what each candidate preference would lead the player to do. When a correct previous belief is supplied, carry it forward and apply the new evidence. Your answer must match the conclusion in your explanation.
Submit one SUBMIT_BELIEFS call. Its arguments contain judgments: a one-element list of objects with player, goal, possible_preferences (a list), and favored. Do not take a game action.

### Local teacher check (never sent to learner)

```json
{
  "gold": {
    "possible_preferences": [
      "want",
      "neutral"
    ],
    "favored": "undetermined"
  },
  "completed_goals": {
    "ACCEPT": [
      true,
      false
    ],
    "REJECT": [
      false,
      false
    ]
  },
  "world_checks": [
    {
      "preference": "want",
      "responder_preferences": [
        1,
        1
      ],
      "payoffs": {
        "ACCEPT": [
          1,
          1
        ],
        "REJECT": [
          0,
          0
        ]
      },
      "response_likelihood": {
        "ACCEPT": "1",
        "REJECT": "0"
      }
    },
    {
      "preference": "neutral",
      "responder_preferences": [
        0,
        1
      ],
      "payoffs": {
        "ACCEPT": [
          1,
          0
        ],
        "REJECT": [
          0,
          0
        ]
      },
      "response_likelihood": {
        "ACCEPT": "1",
        "REJECT": "0"
      }
    },
    {
      "preference": "avoid",
      "responder_preferences": [
        -1,
        1
      ],
      "payoffs": {
        "ACCEPT": [
          1,
          -1
        ],
        "REJECT": [
          0,
          0
        ]
      },
      "response_likelihood": {
        "ACCEPT": "0",
        "REJECT": "1"
      }
    }
  ],
  "posterior": {
    "want": "1/2",
    "neutral": "1/2",
    "avoid": "0"
  },
  "scope": "Exact final-response check; responder knows every fact used in their payoff comparison."
}
```

## Lesson level 2: ed731ab1d7acb047447f

GAME RULES
1. Goals and commitments: A goal is achieved when ALL its listed player-specific commitments are binding. A player's preference does not change this condition. One binding commitment can contribute to several goals without completing all of them.
2. Payoffs: At the end of the game, each achieved goal gives each player +1 for want, 0 for neutral, or -1 for avoid. An unachieved goal gives everyone 0. Each player's final score is the sum of their scores from all goals.
3. Offers: OFFER proposes NEW commitments for the proposer and partner. These are commitments each player will undertake, not items transferred between players. ACCEPT binds all proposed additions; REJECT binds none. Existing binding commitments cannot be removed.
4. Timing: A proposal and its response together use one proposal opportunity. PASS uses that opportunity without adding commitments. Players follow the remaining proposal order shown below. The game ends after the final opportunity, including its response if an offer was made.
5. Investigation: Each player can investigate once per game. INVESTIGATE spends the current proposal opportunity and that use. Choose any other player and any goal. The environment reveals that player's true preference for the goal only to the investigator. Everyone sees who investigated whom about which goal. Each player knows their own preferences.

YOUR ROLE AND TASK
You are Alex.
Assess the requested belief; do not take a game action.

GOALS AND COMMITMENTS
- Orchard requires Alex to commit to Cedar and Blair to commit to Cedar.
- Harbor requires Alex to commit to Cedar and Blair to commit to Cedar.
Already binding (currently in force):
- Alex: none.
- Blair: none.
Commitment options still available to add (not yet binding):
- Alex: Cedar.
- Blair: Cedar.
An offer may add at most 1 new commitment(s) per involved player.

WHAT YOU KNOW
- You want to avoid Orchard. Everyone knows this preference.
- You want Harbor. Everyone knows this preference.
- Blair wants Harbor. Everyone knows this preference.
Correct PREVIOUS belief about Blair / Orchard (before the new evidence): possible_preferences=["want", "neutral", "avoid"], favored=undetermined.

HOW PREFERENCES ARE DRAWN
The preferences known to everyone are fixed. Initially, each other preference is drawn independently with equal chances of want, neutral and avoid. Draws are repeated until each player wants at least one goal and each goal has at least one player who is not neutral about it. Everyone knows these rules; there are no other restrictions on preferences.

HOW OTHER PLAYERS CHOOSE
Other players plan for the end of the game using the actions everyone has seen, their own preferences and their own investigation answers. They choose actions that maximize their expected final score. On a tie, they prefer the highest total expected score for the other players. If actions still tie, they choose equally at random among them.

HISTORY VISIBLE TO EVERYONE
Starting events were provided by the task, independently of preferences, rather than chosen by players. They do not reveal what a player prefers.
1. [earlier history] Starting event provided by the task: Blair passes. No commitments are added.
2. [earlier history] Starting event provided by the task: Alex proposes to Blair: Alex would add Cedar; Blair would add Cedar. This proposal alone binds nothing.
3. [new evidence] Blair chose to reject Alex's offer. No proposed additions become binding.

CURRENT DECISION
No proposal opportunities remain; the game history is complete.
Investigation uses remaining: Alex=1; Blair=1.
Assess ONLY Blair's preference for Orchard.
possible_preferences is the set of values STILL compatible with the available evidence, not a list of all preference words. A true revealed value leaves only that value. favored is the uniquely most supported remaining value, even when other values remain possible; use undetermined if the top support is tied. Undetermined does not mean all values are equally supported. Keep all three values when all three remain compatible; exclude a value only with a valid reason. Compare the observed choices with what each candidate preference would lead the player to do. When a correct previous belief is supplied, carry it forward and apply the new evidence. Your answer must match the conclusion in your explanation.
Submit one SUBMIT_BELIEFS call. Its arguments contain judgments: a one-element list of objects with player, goal, possible_preferences (a list), and favored. Do not take a game action.

### Local teacher check (never sent to learner)

```json
{
  "gold": {
    "possible_preferences": [
      "avoid"
    ],
    "favored": "avoid"
  },
  "completed_goals": {
    "ACCEPT": [
      true,
      true
    ],
    "REJECT": [
      false,
      false
    ]
  },
  "world_checks": [
    {
      "preference": "want",
      "responder_preferences": [
        1,
        1
      ],
      "payoffs": {
        "ACCEPT": [
          0,
          2
        ],
        "REJECT": [
          0,
          0
        ]
      },
      "response_likelihood": {
        "ACCEPT": "1",
        "REJECT": "0"
      }
    },
    {
      "preference": "neutral",
      "responder_preferences": [
        0,
        1
      ],
      "payoffs": {
        "ACCEPT": [
          0,
          1
        ],
        "REJECT": [
          0,
          0
        ]
      },
      "response_likelihood": {
        "ACCEPT": "1",
        "REJECT": "0"
      }
    },
    {
      "preference": "avoid",
      "responder_preferences": [
        -1,
        1
      ],
      "payoffs": {
        "ACCEPT": [
          0,
          0
        ],
        "REJECT": [
          0,
          0
        ]
      },
      "response_likelihood": {
        "ACCEPT": "1/2",
        "REJECT": "1/2"
      }
    }
  ],
  "posterior": {
    "want": "0",
    "neutral": "0",
    "avoid": "1"
  },
  "scope": "Exact final-response check; responder knows every fact used in their payoff comparison."
}
```

## Lesson level 3: cabfe149a8d3ebf3b237

GAME RULES
1. Goals and commitments: A goal is achieved when ALL its listed player-specific commitments are binding. A player's preference does not change this condition. One binding commitment can contribute to several goals without completing all of them.
2. Payoffs: At the end of the game, each achieved goal gives each player +1 for want, 0 for neutral, or -1 for avoid. An unachieved goal gives everyone 0. Each player's final score is the sum of their scores from all goals.
3. Offers: OFFER proposes NEW commitments for the proposer and partner. These are commitments each player will undertake, not items transferred between players. ACCEPT binds all proposed additions; REJECT binds none. Existing binding commitments cannot be removed.
4. Timing: A proposal and its response together use one proposal opportunity. PASS uses that opportunity without adding commitments. Players follow the remaining proposal order shown below. The game ends after the final opportunity, including its response if an offer was made.
5. Investigation: Each player can investigate once per game. INVESTIGATE spends the current proposal opportunity and that use. Choose any other player and any goal. The environment reveals that player's true preference for the goal only to the investigator. Everyone sees who investigated whom about which goal. Each player knows their own preferences.

YOUR ROLE AND TASK
You are Alex.
Assess the requested belief; do not take a game action.

GOALS AND COMMITMENTS
- Orchard requires Alex to commit to Cedar and Blair to commit to Cedar.
- Harbor requires Alex to commit to Cedar and Blair to commit to Cedar.
- Library requires Alex to commit to Maple and Blair to commit to Maple.
Already binding (currently in force):
- Alex: Cedar.
- Blair: Cedar.
Commitment options still available to add (not yet binding):
- Alex: Maple.
- Blair: Maple.
An offer may add at most 1 new commitment(s) per involved player.

WHAT YOU KNOW
- You want Orchard. Everyone knows this preference.
- You want to avoid Harbor. Everyone knows this preference.
- You want Library. Everyone knows this preference.
- Blair is neutral about Harbor. Everyone knows this preference.
- Blair wants Library. Everyone knows this preference.
Correct PREVIOUS belief about Blair / Orchard (before the new evidence): possible_preferences=["want", "neutral", "avoid"], favored=undetermined.

HOW PREFERENCES ARE DRAWN
The preferences known to everyone are fixed. Initially, each other preference is drawn independently with equal chances of want, neutral and avoid. Draws are repeated until each player wants at least one goal and each goal has at least one player who is not neutral about it. Everyone knows these rules; there are no other restrictions on preferences.

HOW OTHER PLAYERS CHOOSE
Other players plan for the end of the game using the actions everyone has seen, their own preferences and their own investigation answers. They choose actions that maximize their expected final score. On a tie, they prefer the highest total expected score for the other players. If actions still tie, they choose equally at random among them.

HISTORY VISIBLE TO EVERYONE
Starting events were provided by the task, independently of preferences, rather than chosen by players. They do not reveal what a player prefers.
1. [earlier history] Starting event provided by the task: Blair passes. No commitments are added.
2. [earlier history] Starting event provided by the task: Alex proposes to Blair: Alex would add Cedar; Blair would add Cedar. This proposal alone binds nothing.
3. [new evidence] Blair chose to accept Alex's offer. New binding commitments: Alex: Cedar; Blair: Cedar.

CURRENT DECISION
No proposal opportunities remain; the game history is complete.
Investigation uses remaining: Alex=1; Blair=1.
Assess ONLY Blair's preference for Orchard.
possible_preferences is the set of values STILL compatible with the available evidence, not a list of all preference words. A true revealed value leaves only that value. favored is the uniquely most supported remaining value, even when other values remain possible; use undetermined if the top support is tied. Undetermined does not mean all values are equally supported. Keep all three values when all three remain compatible; exclude a value only with a valid reason. Compare the observed choices with what each candidate preference would lead the player to do. When a correct previous belief is supplied, carry it forward and apply the new evidence. Your answer must match the conclusion in your explanation.
Submit one SUBMIT_BELIEFS call. Its arguments contain judgments: a one-element list of objects with player, goal, possible_preferences (a list), and favored. Do not take a game action.

### Local teacher check (never sent to learner)

```json
{
  "gold": {
    "possible_preferences": [
      "want",
      "neutral"
    ],
    "favored": "want"
  },
  "completed_goals": {
    "ACCEPT": [
      true,
      true,
      false
    ],
    "REJECT": [
      false,
      false,
      false
    ]
  },
  "world_checks": [
    {
      "preference": "want",
      "responder_preferences": [
        1,
        0,
        1
      ],
      "payoffs": {
        "ACCEPT": [
          0,
          1
        ],
        "REJECT": [
          0,
          0
        ]
      },
      "response_likelihood": {
        "ACCEPT": "1",
        "REJECT": "0"
      }
    },
    {
      "preference": "neutral",
      "responder_preferences": [
        0,
        0,
        1
      ],
      "payoffs": {
        "ACCEPT": [
          0,
          0
        ],
        "REJECT": [
          0,
          0
        ]
      },
      "response_likelihood": {
        "ACCEPT": "1/2",
        "REJECT": "1/2"
      }
    },
    {
      "preference": "avoid",
      "responder_preferences": [
        -1,
        0,
        1
      ],
      "payoffs": {
        "ACCEPT": [
          0,
          -1
        ],
        "REJECT": [
          0,
          0
        ]
      },
      "response_likelihood": {
        "ACCEPT": "0",
        "REJECT": "1"
      }
    }
  ],
  "posterior": {
    "want": "2/3",
    "neutral": "1/3",
    "avoid": "0"
  },
  "scope": "Exact final-response check; responder knows every fact used in their payoff comparison."
}
```

## Lesson level 4: 42f514c50d2e9a21657e

GAME RULES
1. Goals and commitments: A goal is achieved when ALL its listed player-specific commitments are binding. A player's preference does not change this condition. One binding commitment can contribute to several goals without completing all of them.
2. Payoffs: At the end of the game, each achieved goal gives each player +1 for want, 0 for neutral, or -1 for avoid. An unachieved goal gives everyone 0. Each player's final score is the sum of their scores from all goals.
3. Offers: OFFER proposes NEW commitments for the proposer and partner. These are commitments each player will undertake, not items transferred between players. ACCEPT binds all proposed additions; REJECT binds none. Existing binding commitments cannot be removed.
4. Timing: A proposal and its response together use one proposal opportunity. PASS uses that opportunity without adding commitments. Players follow the remaining proposal order shown below. The game ends after the final opportunity, including its response if an offer was made.
5. Investigation: Each player can investigate once per game. INVESTIGATE spends the current proposal opportunity and that use. Choose any other player and any goal. The environment reveals that player's true preference for the goal only to the investigator. Everyone sees who investigated whom about which goal. Each player knows their own preferences.

YOUR ROLE AND TASK
You are Blair.
Assess the requested belief; do not take a game action.

GOALS AND COMMITMENTS
- Harbor requires Blair to commit to Maple and Alex to commit to Maple.
- Orchard requires Blair to commit to Willow and Alex to commit to Maple.
Already binding (currently in force):
- Blair: Willow.
- Alex: Maple.
Commitment options still available to add (not yet binding):
- Blair: Maple.
- Alex: none.
An offer may add at most 1 new commitment(s) per involved player.

WHAT YOU KNOW
- You want Harbor. Everyone knows this preference.
- You want to avoid Orchard. Everyone knows this preference.
Correct PREVIOUS belief about Alex / Harbor (before the new evidence): possible_preferences=["want", "neutral", "avoid"], favored=want.

HOW PREFERENCES ARE DRAWN
The preferences known to everyone are fixed. Initially, each other preference is drawn independently with equal chances of want, neutral and avoid. Draws are repeated until each player wants at least one goal and each goal has at least one player who is not neutral about it. Everyone knows these rules; there are no other restrictions on preferences.

HOW OTHER PLAYERS CHOOSE
Other players plan for the end of the game using the actions everyone has seen, their own preferences and their own investigation answers. They choose actions that maximize their expected final score. On a tie, they prefer the highest total expected score for the other players. If actions still tie, they choose equally at random among them.

HISTORY VISIBLE TO EVERYONE
Starting events were provided by the task, independently of preferences, rather than chosen by players. They do not reveal what a player prefers.
1. [earlier history] Starting event provided by the task: Alex passes. No commitments are added.
2. [earlier history] Starting event provided by the task: Blair proposes to Alex: Blair would add Willow; Alex would add Maple. This proposal alone binds nothing.
3. [new evidence] Alex chose to accept Blair's offer. New binding commitments: Blair: Willow; Alex: Maple.

CURRENT DECISION
No proposal opportunities remain; the game history is complete.
Investigation uses remaining: Blair=1; Alex=1.
Assess ONLY Alex's preference for Harbor.
possible_preferences is the set of values STILL compatible with the available evidence, not a list of all preference words. A true revealed value leaves only that value. favored is the uniquely most supported remaining value, even when other values remain possible; use undetermined if the top support is tied. Undetermined does not mean all values are equally supported. Keep all three values when all three remain compatible; exclude a value only with a valid reason. Compare the observed choices with what each candidate preference would lead the player to do. When a correct previous belief is supplied, carry it forward and apply the new evidence. Your answer must match the conclusion in your explanation.
Submit one SUBMIT_BELIEFS call. Its arguments contain judgments: a one-element list of objects with player, goal, possible_preferences (a list), and favored. Do not take a game action.

### Local teacher check (never sent to learner)

```json
{
  "gold": {
    "possible_preferences": [
      "want",
      "neutral",
      "avoid"
    ],
    "favored": "undetermined"
  },
  "completed_goals": {
    "ACCEPT": [
      false,
      true
    ],
    "REJECT": [
      false,
      false
    ]
  },
  "world_checks": [
    {
      "preference": "want",
      "responder_preferences": [
        1,
        1
      ],
      "payoffs": {
        "ACCEPT": [
          -1,
          1
        ],
        "REJECT": [
          0,
          0
        ]
      },
      "response_likelihood": {
        "ACCEPT": "1",
        "REJECT": "0"
      }
    },
    {
      "preference": "want",
      "responder_preferences": [
        1,
        0
      ],
      "payoffs": {
        "ACCEPT": [
          -1,
          0
        ],
        "REJECT": [
          0,
          0
        ]
      },
      "response_likelihood": {
        "ACCEPT": "0",
        "REJECT": "1"
      }
    },
    {
      "preference": "want",
      "responder_preferences": [
        1,
        -1
      ],
      "payoffs": {
        "ACCEPT": [
          -1,
          -1
        ],
        "REJECT": [
          0,
          0
        ]
      },
      "response_likelihood": {
        "ACCEPT": "0",
        "REJECT": "1"
      }
    },
    {
      "preference": "neutral",
      "responder_preferences": [
        0,
        1
      ],
      "payoffs": {
        "ACCEPT": [
          -1,
          1
        ],
        "REJECT": [
          0,
          0
        ]
      },
      "response_likelihood": {
        "ACCEPT": "1",
        "REJECT": "0"
      }
    },
    {
      "preference": "avoid",
      "responder_preferences": [
        -1,
        1
      ],
      "payoffs": {
        "ACCEPT": [
          -1,
          1
        ],
        "REJECT": [
          0,
          0
        ]
      },
      "response_likelihood": {
        "ACCEPT": "1",
        "REJECT": "0"
      }
    }
  ],
  "posterior": {
    "want": "1/3",
    "neutral": "1/3",
    "avoid": "1/3"
  },
  "scope": "Exact final-response check; responder knows every fact used in their payoff comparison."
}
```
