import sys
import math
import torch
import torch.nn as nn

# TODO: find a better solution
if sys.gettrace() is not None:  # Debug Mode
    # Note: this should be used when ran from PyCharm be in Debug mode or normal mode
    # Original
    # from models.neural import MultiHeadedAttention, PositionwiseFeedForward
    from .neural import MultiHeadedAttention, PositionwiseFeedForward
else:
    # Use this when running from terminal
    from .neural import MultiHeadedAttention, PositionwiseFeedForward


class PositionalEncoding(nn.Module):
    def __init__(self, dropout, dim, max_len=5000):
        pe = torch.zeros(max_len, dim)
        position = torch.arange(0, max_len).unsqueeze(1)
        div_term = torch.exp(
            (torch.arange(0, dim, 2, dtype=torch.float) * -(math.log(10000.0) / dim))
        )
        pe[:, 0::2] = torch.sin(position.float() * div_term)
        pe[:, 1::2] = torch.cos(position.float() * div_term)
        pe = pe.unsqueeze(0)
        super().__init__()
        self.register_buffer("pe", pe)
        self.dropout = nn.Dropout(p=dropout)
        self.dim = dim

    def forward(self, emb, step=None):
        emb = emb * math.sqrt(self.dim)
        if step:
            emb = emb + self.pe[:, step][:, None, :]

        else:
            emb = emb + self.pe[:, : emb.size(1)]
        emb = self.dropout(emb)
        return emb

    def get_emb(self, emb):
        return self.pe[:, : emb.size(1)]


class TransformerEncoderLayer(nn.Module):
    def __init__(self, d_model, heads, d_ff, dropout):
        super().__init__()

        self.self_attn = MultiHeadedAttention(heads, d_model, dropout=dropout)
        self.feed_forward = PositionwiseFeedForward(d_model, d_ff, dropout)
        self.layer_norm = nn.LayerNorm(d_model, eps=1e-6)
        self.dropout = nn.Dropout(dropout)

    def forward(self, iter, query, inputs, mask):
        if iter != 0:
            input_norm = self.layer_norm(inputs)
        else:
            input_norm = inputs

        mask = mask.unsqueeze(1)
        context = self.self_attn(input_norm, input_norm, input_norm, mask=mask)
        out = self.dropout(context) + inputs
        return self.feed_forward(out)


class ExtTransformerEncoder(nn.Module):
    def __init__(self, d_model, d_ff, heads, dropout, num_inter_layers=0):
        super().__init__()
        self.d_model = d_model
        self.num_inter_layers = num_inter_layers
        self.pos_emb = PositionalEncoding(dropout, d_model)
        self.transformer_inter = nn.ModuleList(
            [
                TransformerEncoderLayer(d_model, heads, d_ff, dropout)
                for _ in range(num_inter_layers)
            ]
        )
        self.dropout = nn.Dropout(dropout)
        self.layer_norm = nn.LayerNorm(d_model, eps=1e-6)
        self.wo = nn.Linear(d_model, 1, bias=True)
        self.sigmoid = nn.Sigmoid()

    def forward(self, top_vecs, mask, my_flag: bool = False):
        """See :obj:`EncoderBase.forward()`"""

        batch_size, n_sents = top_vecs.size(0), top_vecs.size(1)
        pos_emb = self.pos_emb.pe[
            :, :n_sents
        ]  # in total there are 5K pos_embeddings. So not an issue
        x = top_vecs * mask[:, :, None].float()
        x = x + pos_emb

        for i in range(self.num_inter_layers):
            # TODO: Check why he is doing (1 - mask)
            #   As such he has done (1 - mask) in training code as well
            x = self.transformer_inter[i](
                i, x, x, 1 - mask
            )  # all_sents * max_tokens * dim

        x = self.layer_norm(x)
        if (
            my_flag
        ):  # This is done because we want vectors that'll be used by LSTM Decode
            return x

        sent_scores = self.sigmoid(self.wo(x))  # out = [batch*1]
        sent_scores = sent_scores.squeeze(-1) * mask.float()
        return sent_scores
