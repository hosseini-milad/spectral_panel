import torch
from torch import nn
from torch.nn import functional as F


class EigenvectorAwareMessageLayer(nn.Module):
    """Directed message passing conditioned on sign-invariant spectral PE."""

    def __init__(self, hidden_dim, pe_dim, edge_dim, scale_dim):
        super().__init__()
        message_dim = hidden_dim * 2 + pe_dim * 3 + edge_dim + scale_dim
        self.message = nn.Sequential(
            nn.Linear(message_dim, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
        )
        self.update = nn.Sequential(
            nn.Linear(hidden_dim * 3, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, hidden_dim),
        )
        self.norm = nn.LayerNorm(hidden_dim)

    def forward(self, hidden, positional, edge_index, edge_features, scale_features):
        count = hidden.shape[0]
        source, target = edge_index
        h_source, h_target = hidden[source], hidden[target]
        p_source, p_target = positional[source], positional[target]
        scale_per_edge = scale_features.expand(source.shape[0], -1)
        message_input = torch.cat(
            [
                h_source,
                h_target,
                p_source.abs(),
                p_target.abs(),
                p_source * p_target,
                edge_features,
                scale_per_edge,
            ],
            dim=-1,
        )
        messages = self.message(message_input)

        incoming = torch.zeros_like(hidden)
        outgoing = torch.zeros_like(hidden)
        incoming.index_add_(0, target, messages)
        outgoing.index_add_(0, source, messages)
        in_degree = torch.zeros((count, 1), device=hidden.device, dtype=hidden.dtype)
        out_degree = torch.zeros_like(in_degree)
        ones = torch.ones((messages.shape[0], 1), device=hidden.device, dtype=hidden.dtype)
        in_degree.index_add_(0, target, ones)
        out_degree.index_add_(0, source, ones)
        incoming = incoming / in_degree.clamp_min(1.0)
        outgoing = outgoing / out_degree.clamp_min(1.0)
        updated = self.update(torch.cat([hidden, incoming, outgoing], dim=-1))
        return self.norm(hidden + updated)


class EigenvectorAwareGraphEncoder(nn.Module):
    def __init__(
        self,
        input_dim,
        pe_dim=8,
        edge_dim=3,
        hidden_dim=64,
        embedding_dim=32,
        layer_count=2,
        scale_count=3,
        scale_dim=4,
    ):
        super().__init__()
        self.input_dim = input_dim
        self.pe_dim = pe_dim
        self.edge_dim = edge_dim
        self.hidden_dim = hidden_dim
        self.embedding_dim = embedding_dim
        self.scale_embedding = nn.Embedding(scale_count, scale_dim)
        self.input_projection = nn.Sequential(
            nn.Linear(input_dim + pe_dim + scale_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.layers = nn.ModuleList(
            [
                EigenvectorAwareMessageLayer(hidden_dim, pe_dim, edge_dim, scale_dim)
                for _ in range(layer_count)
            ]
        )
        self.embedding_projection = nn.Sequential(
            nn.Linear(hidden_dim, embedding_dim),
            nn.LayerNorm(embedding_dim),
        )
        self.feature_decoder = nn.Linear(embedding_dim, input_dim)
        self.spectral_decoder = nn.Linear(embedding_dim, pe_dim)
        self.link_source = nn.Linear(embedding_dim, embedding_dim, bias=False)
        self.link_target = nn.Linear(embedding_dim, embedding_dim, bias=False)

    def encode(self, features, positional, edge_index, edge_features, scale_id):
        scale_features = self.scale_embedding(scale_id.reshape(1)).reshape(1, -1)
        scale_per_node = scale_features.expand(features.shape[0], -1)
        hidden = self.input_projection(
            torch.cat([features, positional.abs(), scale_per_node], dim=-1)
        )
        for layer in self.layers:
            hidden = layer(
                hidden, positional, edge_index, edge_features, scale_features
            )
        return self.embedding_projection(hidden)

    def decode_links(self, embeddings, pairs):
        source = self.link_source(embeddings[pairs[:, 0]])
        target = self.link_target(embeddings[pairs[:, 1]])
        return (source * target).sum(dim=-1) / (self.embedding_dim ** 0.5)

    def reconstruct_features(self, embeddings):
        return self.feature_decoder(embeddings)

    def predict_spectrum(self, embeddings):
        """Predict sign-invariant spectral positional encodings per node."""
        return self.spectral_decoder(embeddings)
