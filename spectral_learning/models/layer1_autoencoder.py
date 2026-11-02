"""Shared masked graph autoencoder with symmetric pair and feature decoders."""
import torch
from torch import nn
from .eigenvector_gnn import EigenvectorAwareMessagePassing


class Layer1Autoencoder(nn.Module):
    def __init__(self, input_dim, hidden_dim=64, latent_dim=16, layers=2, variant='spectral'):
        super().__init__()
        if variant not in {'feature', 'graph', 'spectral'}:
            raise ValueError('Unknown autoencoder variant')
        self.variant = variant
        self.encoder = EigenvectorAwareMessagePassing(input_dim, hidden_dim=hidden_dim,
                                                      layers=0 if variant == 'feature' else layers)
        self.bottleneck = nn.Sequential(nn.GELU(), nn.Linear(hidden_dim, latent_dim))
        self.feature_decoder = nn.Sequential(nn.Linear(latent_dim, hidden_dim), nn.GELU(), nn.Linear(hidden_dim, input_dim))
        self.edge_decoder = nn.Sequential(nn.Linear(2 * latent_dim, hidden_dim), nn.GELU(), nn.Linear(hidden_dim, 2))

    def forward(self, inputs):
        args = list(inputs)
        if self.variant != 'spectral':
            args[2] = torch.zeros_like(args[2]); args[3] = torch.zeros_like(args[3])
            args[6] = torch.zeros_like(args[6]); args[7] = torch.zeros_like(args[7])
        latent = self.bottleneck(self.encoder(*args, level=1))
        return self.feature_decoder(latent), latent

    def decode_pairs(self, latent, pairs):
        left, right = latent[pairs[0]], latent[pairs[1]]
        decoded = self.edge_decoder(torch.cat([left * right, torch.abs(left - right)], dim=1))
        return decoded[:, 0], torch.sigmoid(decoded[:, 1])
