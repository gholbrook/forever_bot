import joblib
import pandas as pd
from sklearn.preprocessing import StandardScaler
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

df = pd.read_parquet('training_data.parquet')

feature_cols = [c for c in df.columns if not c.startswith('act_')]
action_cols = [c for c in df.columns if c.startswith('act_')]

X = df[feature_cols].values.astype('float32')
y = df[action_cols].values.astype('float32')

# Normalize continuous features (coordinates, speed, health, rage)
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)
joblib.dump(
    {'scaler': scaler, 'features': feature_cols, 'actions': action_cols},
    'policy_meta.joblib',
)

dataset = TensorDataset(torch.tensor(X_scaled), torch.tensor(y))
loader = DataLoader(dataset, batch_size=128, shuffle=True)


class WarriorPolicyNet(nn.Module):

  def __init__(self, in_dim, out_dim):
    super().__init__()
    self.net = nn.Sequential(
        nn.Linear(in_dim, 256),
        nn.LayerNorm(256),
        nn.SiLU(),
        nn.Dropout(0.15),
        nn.Linear(256, 256),
        nn.LayerNorm(256),
        nn.SiLU(),
        nn.Dropout(0.15),
        nn.Linear(256, out_dim),
    )

  def forward(self, x):
    return self.net(x)


device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
model = WarriorPolicyNet(len(feature_cols), len(action_cols)).to(device)

# Weight rare combat abilities higher so the model doesn't just hold 'forward'
pos_counts = y.sum(axis=0)
neg_counts = len(y) - pos_counts
pos_weight = torch.tensor(
    (neg_counts / (pos_counts + 1e-5)).clip(1.0, 15.0), device=device
)

criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)

for epoch in range(40):
  model.train()
  total_loss = 0.0
  for bx, by in loader:
    bx, by = bx.to(device), by.to(device)
    optimizer.zero_grad()
    loss = criterion(model(bx), by)
    loss.backward()
    optimizer.step()
    total_loss += loss.item()
  if (epoch + 1) % 10 == 0:
    print(f'Epoch {epoch+1:02d} | Loss: {total_loss/len(loader):.4f}')

torch.save(model.state_dict(), 'warrior_policy.pt')
print('Training complete! Saved warrior_policy.pt and policy_meta.joblib')
