"""SCUNet 네트워크 정의 (Zhang et al. 2022, KAIR network_scunet.py와 같은 구조).

사전학습 가중치: models/scunet_color_real_psnr.pth
"""
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from einops import rearrange


class WMSA(nn.Module):
    def __init__(self, input_dim, output_dim, head_dim, window_size, type):
        super().__init__()
        self.input_dim = input_dim
        self.output_dim = output_dim
        self.head_dim = head_dim
        self.scale = head_dim ** -0.5
        self.n_heads = input_dim // head_dim
        self.window_size = window_size
        self.type = type
        self.embedding_layer = nn.Linear(input_dim, 3 * input_dim, bias=True)
        self.relative_position_params = nn.Parameter(
            torch.zeros(self.n_heads, 2 * window_size - 1, 2 * window_size - 1))
        self.linear = nn.Linear(input_dim, output_dim)
        cord = torch.tensor(np.array([[i, j] for i in range(window_size) for j in range(window_size)]))
        relation = cord[:, None, :] - cord[None, :, :] + window_size - 1
        self.register_buffer("rel_idx", relation.long(), persistent=False)

    def generate_mask(self, h, w, p, shift, device):
        attn_mask = torch.zeros(h, w, p, p, p, p, dtype=torch.bool, device=device)
        if self.type == "W":
            return attn_mask
        s = p - shift
        attn_mask[-1, :, :s, :, s:, :] = True
        attn_mask[-1, :, s:, :, :s, :] = True
        attn_mask[:, -1, :, :s, :, s:] = True
        attn_mask[:, -1, :, s:, :, :s] = True
        return rearrange(attn_mask, "w1 w2 p1 p2 p3 p4 -> 1 1 (w1 w2) (p1 p2) (p3 p4)")

    def relative_embedding(self):
        return self.relative_position_params[:, self.rel_idx[:, :, 0], self.rel_idx[:, :, 1]]

    def forward(self, x):
        ws = self.window_size
        if self.type != "W":
            x = torch.roll(x, shifts=(-(ws // 2), -(ws // 2)), dims=(1, 2))
        x = rearrange(x, "b (w1 p1) (w2 p2) c -> b w1 w2 p1 p2 c", p1=ws, p2=ws)
        h_windows, w_windows = x.size(1), x.size(2)
        x = rearrange(x, "b w1 w2 p1 p2 c -> b (w1 w2) (p1 p2) c", p1=ws, p2=ws)
        qkv = self.embedding_layer(x)
        q, k, v = rearrange(qkv, "b nw np (threeh c) -> threeh b nw np c", c=self.head_dim).chunk(3, dim=0)
        sim = torch.einsum("hbwpc,hbwqc->hbwpq", q, k) * self.scale
        sim = sim + rearrange(self.relative_embedding(), "h p q -> h 1 1 p q")
        if self.type != "W":
            mask = self.generate_mask(h_windows, w_windows, ws, ws // 2, x.device)
            sim = sim.masked_fill(mask, float("-inf"))
        probs = F.softmax(sim, dim=-1)
        out = torch.einsum("hbwij,hbwjc->hbwic", probs, v)
        out = rearrange(out, "h b w p c -> b w p (h c)")
        out = self.linear(out)
        out = rearrange(out, "b (w1 w2) (p1 p2) c -> b (w1 p1) (w2 p2) c", w1=h_windows, p1=ws)
        if self.type != "W":
            out = torch.roll(out, shifts=(ws // 2, ws // 2), dims=(1, 2))
        return out


class Block(nn.Module):
    def __init__(self, input_dim, output_dim, head_dim, window_size, type="W"):
        super().__init__()
        self.ln1 = nn.LayerNorm(input_dim)
        self.msa = WMSA(input_dim, input_dim, head_dim, window_size, type)
        self.ln2 = nn.LayerNorm(input_dim)
        self.mlp = nn.Sequential(nn.Linear(input_dim, 4 * input_dim), nn.GELU(), nn.Linear(4 * input_dim, output_dim))

    def forward(self, x):
        x = x + self.msa(self.ln1(x))
        x = x + self.mlp(self.ln2(x))
        return x


class ConvTransBlock(nn.Module):
    def __init__(self, conv_dim, trans_dim, head_dim, window_size, type="W"):
        super().__init__()
        self.conv_dim = conv_dim
        self.trans_dim = trans_dim
        self.trans_block = Block(trans_dim, trans_dim, head_dim, window_size, type)
        self.conv1_1 = nn.Conv2d(conv_dim + trans_dim, conv_dim + trans_dim, 1, 1, 0, bias=True)
        self.conv1_2 = nn.Conv2d(conv_dim + trans_dim, conv_dim + trans_dim, 1, 1, 0, bias=True)
        self.conv_block = nn.Sequential(
            nn.Conv2d(conv_dim, conv_dim, 3, 1, 1, bias=False),
            nn.ReLU(True),
            nn.Conv2d(conv_dim, conv_dim, 3, 1, 1, bias=False),
        )

    def forward(self, x):
        conv_x, trans_x = torch.split(self.conv1_1(x), (self.conv_dim, self.trans_dim), dim=1)
        conv_x = self.conv_block(conv_x) + conv_x
        trans_x = rearrange(trans_x, "b c h w -> b h w c")
        trans_x = self.trans_block(trans_x)
        trans_x = rearrange(trans_x, "b h w c -> b c h w")
        return x + self.conv1_2(torch.cat((conv_x, trans_x), dim=1))


class SCUNet(nn.Module):
    def __init__(self, in_nc=3, config=(4, 4, 4, 4, 4, 4, 4), dim=64):
        super().__init__()
        hd, ws = 32, 8
        t = lambda i: "W" if not i % 2 else "SW"
        self.m_head = nn.Sequential(nn.Conv2d(in_nc, dim, 3, 1, 1, bias=False))
        self.m_down1 = nn.Sequential(*[ConvTransBlock(dim // 2, dim // 2, hd, ws, t(i)) for i in range(config[0])],
                                     nn.Conv2d(dim, 2 * dim, 2, 2, 0, bias=False))
        self.m_down2 = nn.Sequential(*[ConvTransBlock(dim, dim, hd, ws, t(i)) for i in range(config[1])],
                                     nn.Conv2d(2 * dim, 4 * dim, 2, 2, 0, bias=False))
        self.m_down3 = nn.Sequential(*[ConvTransBlock(2 * dim, 2 * dim, hd, ws, t(i)) for i in range(config[2])],
                                     nn.Conv2d(4 * dim, 8 * dim, 2, 2, 0, bias=False))
        self.m_body = nn.Sequential(*[ConvTransBlock(4 * dim, 4 * dim, hd, ws, t(i)) for i in range(config[3])])
        self.m_up3 = nn.Sequential(nn.ConvTranspose2d(8 * dim, 4 * dim, 2, 2, 0, bias=False),
                                   *[ConvTransBlock(2 * dim, 2 * dim, hd, ws, t(i)) for i in range(config[4])])
        self.m_up2 = nn.Sequential(nn.ConvTranspose2d(4 * dim, 2 * dim, 2, 2, 0, bias=False),
                                   *[ConvTransBlock(dim, dim, hd, ws, t(i)) for i in range(config[5])])
        self.m_up1 = nn.Sequential(nn.ConvTranspose2d(2 * dim, dim, 2, 2, 0, bias=False),
                                   *[ConvTransBlock(dim // 2, dim // 2, hd, ws, t(i)) for i in range(config[6])])
        self.m_tail = nn.Sequential(nn.Conv2d(dim, in_nc, 3, 1, 1, bias=False))

    def forward(self, x0):
        h, w = x0.shape[-2:]
        pb = int(np.ceil(h / 64) * 64 - h)
        pr = int(np.ceil(w / 64) * 64 - w)
        x0 = F.pad(x0, (0, pr, 0, pb), mode="replicate")
        x1 = self.m_head(x0)
        x2 = self.m_down1(x1)
        x3 = self.m_down2(x2)
        x4 = self.m_down3(x3)
        x = self.m_body(x4)
        x = self.m_up3(x + x4)
        x = self.m_up2(x + x3)
        x = self.m_up1(x + x2)
        x = self.m_tail(x + x1)
        return x[..., :h, :w]
