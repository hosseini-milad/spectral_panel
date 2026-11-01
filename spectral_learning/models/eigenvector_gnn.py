"""Eigenvector-aware encoder used by phase-2 masked-feature probes."""
import torch
from torch import nn


class EigenvectorAwareMessagePassing(nn.Module):
    """Consume eigenspace-invariant signatures, not arbitrary eigenvector signs.

    Inputs use the node/edge ordering and masks in the phase-1 NPZ package.
    Structural hierarchy level is independent of temporal window.
    """
    def __init__(self, input_dim, hidden_dim=64, layers=2, level_count=8, level_dim=8):
        super().__init__()
        self.level = nn.Embedding(level_count, level_dim)
        self.project = nn.Linear(input_dim * 2 + 4 + level_dim, hidden_dim)
        self.messages = nn.ModuleList([nn.Sequential(nn.Linear(hidden_dim * 2 + 4, hidden_dim), nn.GELU(),
                                                     nn.Linear(hidden_dim, hidden_dim)) for _ in range(layers)])
        self.updates = nn.ModuleList([nn.Sequential(nn.Linear(hidden_dim * 2, hidden_dim), nn.GELU(),
                                                    nn.LayerNorm(hidden_dim)) for _ in range(layers)])

    def forward(self, features, feature_mask, node_spectral, node_spectral_mask,
                edge_index, edge_weight, edge_spectral, edge_spectral_mask, level):
        level_values = self.level(torch.as_tensor(level, dtype=torch.long, device=features.device).reshape(1)).expand(len(features), -1)
        node_valid = node_spectral_mask[:, None]
        hidden = self.project(torch.cat([features.masked_fill(~feature_mask, 0), feature_mask.to(features.dtype),
                                        node_spectral * node_valid, node_valid.to(features.dtype), level_values], dim=1))
        source = torch.cat([edge_index[0], edge_index[1]])
        target = torch.cat([edge_index[1], edge_index[0]])
        weights = torch.cat([edge_weight, edge_weight])[:, None]
        valid = torch.cat([edge_spectral_mask, edge_spectral_mask])[:, None]
        positional = torch.cat([edge_spectral, edge_spectral]) * valid
        edge_input = torch.cat([positional, valid.to(features.dtype)], dim=1)
        for message, update in zip(self.messages, self.updates):
            values = message(torch.cat([hidden[source], hidden[target], edge_input], dim=1)) * weights
            aggregate = torch.zeros_like(hidden).index_add_(0, target, values)
            degree = features.new_zeros((len(features), 1)).index_add_(0, target, weights)
            aggregate = aggregate / degree.clamp_min(1e-8)
            hidden = hidden + update(torch.cat([hidden, aggregate], dim=1))
        return hidden
