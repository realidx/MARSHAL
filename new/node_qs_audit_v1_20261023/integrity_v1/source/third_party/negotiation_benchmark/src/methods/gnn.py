"""
gnn.py

Optional GNN model definitions and inference helpers for negotiation states.
"""

import numpy as np
import torch
import torch.nn.functional as F

try:
    from torch_geometric.nn import GATv2Conv
except ImportError:  # pragma: no cover - optional dependency
    GATv2Conv = None



class NegotiatorGNN(torch.nn.Module if torch is not None else object):
    """
    Graph-attention model for estimating player values from negotiation state.
    """

    def __init__(self, num_goals, hidden_dim=64, heads=4):
        if torch is None or GATv2Conv is None:
            raise ImportError(
                "NegotiatorGNN requires both 'torch' and 'torch-geometric' to be installed."
            )

        super().__init__()

        input_dim = (9 * num_goals) + 2 # Based on get_gnn_features output size
        
        self.gat = GATv2Conv(input_dim, hidden_dim, heads=heads, concat=True)
        # self.gat2 = GATv2Conv(hidden_dim * heads, hidden_dim, heads=heads, concat=True)

        self.final_mlp = torch.nn.Sequential(
            torch.nn.Linear(input_dim + hidden_dim * heads, hidden_dim),
            torch.nn.ReLU(),
            torch.nn.Dropout(0.1),
            torch.nn.Linear(hidden_dim, hidden_dim),
            torch.nn.ReLU(),
            torch.nn.Linear(hidden_dim, 1),
        )

    def forward(self, x, edge_index):
        social_context = self.gat(x, edge_index)
        social_context = F.relu(social_context)
        # social_context = self.gat2(social_context, edge_index)
        # social_context = F.relu(social_context)

        combined = torch.cat([x, social_context], dim=1)
        out = self.final_mlp(combined)
        return out.squeeze(-1)


def estimate_state_payoffs_with_gnn(state, model):
    """
    Run GNN inference for a negotiation state.

    Args:
        state: ``NegotiationState`` with a ``get_gnn_features`` method.
        model: A PyTorch model that maps node features to per-player values.

    Returns:
        np.ndarray: Predicted payoff vector.
    """
    if model is None:
        raise ValueError("GNN evaluation requires a model, but no model was provided.")

    if torch is None:
        raise ImportError("GNN evaluation requires 'torch' to be installed.")

    features = state.get_gnn_features()
    x = torch.tensor(features, dtype=torch.float32)

    dense_adjacency = torch.ones((state.n_players, state.n_players), dtype=torch.long)
    edge_index = dense_adjacency.nonzero(as_tuple=False).t().contiguous()

    was_training = getattr(model, "training", False)
    if hasattr(model, "eval"):
        model.eval()

    with torch.no_grad():
        prediction = model(x, edge_index)

    if was_training and hasattr(model, "train"):
        model.train()

    if hasattr(prediction, "detach"):
        prediction = prediction.detach().cpu().numpy()

    return np.asarray(prediction, dtype=float)
