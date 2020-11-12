import gym
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.distributions import Normal
import numpy as np
import collections, random

#Hyperparameters
lr_pi        = 0.0005
lr_q         = 0.001
alpha        = 0.05
gamma        = 0.98
batch_size   = 32
buffer_limit = 50000
tau           = 0.01 # for target network soft update

class ReplayBuffer():
    def __init__(self):
        self.buffer = collections.deque(maxlen=buffer_limit)

    def put(self, transition):
        self.buffer.append(transition)
    
    def sample(self, n):
        mini_batch = random.sample(self.buffer, n)
        s_lst, a_lst, r_lst, s_prime_lst, done_mask_lst = [], [], [], [], []

        for transition in mini_batch:
            s, a, r, s_prime, done = transition
            s_lst.append(s)
            a_lst.append([a])
            r_lst.append([r])
            s_prime_lst.append(s_prime)
            done_mask = 0.0 if done else 1.0 
            done_mask_lst.append([done_mask])
        
        return torch.tensor(s_lst, dtype=torch.float), torch.tensor(a_lst, dtype=torch.float), \
                torch.tensor(r_lst, dtype=torch.float), torch.tensor(s_prime_lst, dtype=torch.float), \
                torch.tensor(done_mask_lst, dtype=torch.float)
    
    def size(self):
        return len(self.buffer)

class PolicyNet(nn.Module):
    def __init__(self, learning_rate):
        super(PolicyNet, self).__init__()
        self.fc1 = nn.Linear(3, 128)
        self.fc_mu = nn.Linear(128,1)
        self.fc_std  = nn.Linear(128,1)
        self.optimizer = optim.Adam(self.parameters(), lr=learning_rate)

    def forward(self, x):
        x = F.relu(self.fc1(x))
        mu = self.fc_mu(x)
        std = F.softplus(self.fc_std(x))

        zero_mean = torch.zeros_like(mu)
        one_std = torch.zeros_like(std) + 1.0
        dist = Normal(zero_mean, one_std)
        noise = dist.sample()
        log_prob = dist.log_prob(noise)
        action = 2.0 * torch.tanh(mu + std * noise)  # since pendulum's action space is [-2,2]
        return action, log_prob

    def sample_action(self, mu, sigma):
        dist = Normal(mu, sigma)

class QNet(nn.Module):
    def __init__(self, learning_rate):
        super(QNet, self).__init__()
        self.fc_s = nn.Linear(3, 64)
        self.fc_a = nn.Linear(1,64)
        self.fc_cat = nn.Linear(128,32)
        self.fc_out = nn.Linear(32,1)
        self.optimizer = optim.Adam(self.parameters(), lr=learning_rate)

    def forward(self, x, a):
        h1 = F.relu(self.fc_s(x))
        h2 = F.relu(self.fc_a(a))
        cat = torch.cat([h1,h2], dim=1)
        q = F.relu(self.fc_cat(cat))
        q = self.fc_out(q)
        return q

def calc_target(pi, q1, q2, mini_batch):
    s, a, r, s_prime, done = mini_batch

    with torch.no_grad():
        a_prime, log_prob= pi(s_prime)
        entropy = -alpha * log_prob
        q1_val, q2_val = q1(s_prime,a_prime), q2(s_prime,a_prime)
        q1_q2 = torch.cat([q1_val, q2_val], dim=1)
        min_q = torch.min(q1_q2, 1, keepdim=True)[0]
        target = r + gamma * done * (min_q + entropy)

    return target

def train_q(q, target, mini_batch):
    s, a, r, s_prime, done = mini_batch
    loss = F.smooth_l1_loss(q(s, a) , target)
    q.optimizer.zero_grad()
    loss.mean().backward()
    q.optimizer.step()

def train_pi(pi, q1, q2, mini_batch):
    s, a, r, s_prime, done = mini_batch
    a_prime, log_prob = pi(s_prime)
    entropy = -alpha * log_prob

    q1_val, q2_val = q1(s,a_prime), q2(s,a_prime)
    q1_q2 = torch.cat([q1_val, q2_val], dim=1)
    min_q = torch.min(q1_q2, 1, keepdim=True)[0]

    loss = -min_q - entropy # for gradient ascent
    pi.optimizer.zero_grad()
    loss.mean().backward()
    pi.optimizer.step()

def soft_update(net, net_target):
    for param_target, param in zip(net_target.parameters(), net.parameters()):
        param_target.data.copy_(param_target.data * (1.0 - tau) + param.data * tau)
    
def main():
    env = gym.make('Pendulum-v0')
    memory = ReplayBuffer()

    q1, q2, q1_target, q2_target = QNet(lr_q), QNet(lr_q), QNet(lr_q), QNet(lr_q)
    q1_target.load_state_dict(q1.state_dict())
    q2_target.load_state_dict(q2.state_dict())

    pi = PolicyNet(lr_pi)

    score = 0.0
    print_interval = 20

    for n_epi in range(10000):
        s = env.reset()
        done = False
        
        while not done:
            a, log_prob= pi(torch.from_numpy(s).float())
            s_prime, r, done, info = env.step([a.item()])
            memory.put((s, a.item(), r/10.0, s_prime, done))
            score +=r
            s = s_prime
                
        if memory.size()>1000:
            for i in range(20):
                mini_batch = memory.sample(batch_size)
                target = calc_target(pi, q1_target, q2_target, mini_batch)
                train_q(q1, target, mini_batch)
                train_q(q2, target, mini_batch)
                train_pi(pi, q1, q2, mini_batch)
                soft_update(q1, q1_target)
                soft_update(q2, q2_target)
        
        if n_epi%print_interval==0 and n_epi!=0:
            print("# of episode :{}, avg score : {:.1f}".format(n_epi, score/print_interval))
            score = 0.0

    env.close()

if __name__ == '__main__':
    main()