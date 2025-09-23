#!/bin/bash

set -e

SANDBOX_ID="test-net-ci"
IP_ADDRESS="192.168.250.10"
PEER_IP="192.168.250.11"
VETH="veth-ci"
PEER="peer-ci"
NAMESPACE=$SANDBOX_ID

echo "--- Setting up network ---"

# Get the host's default network interface and MTU.
HOST_IF=$(ip route show default | awk '{print $5}')
MTU=$(ip link show $HOST_IF | awk '{print $5}')

# Setup commands
ip link add $VETH mtu $MTU type veth peer name $PEER
ip addr add $PEER_IP/24 dev $PEER
ip link set $PEER up
ip netns add $NAMESPACE
ip link set $VETH netns $NAMESPACE
ip netns exec $NAMESPACE ip addr add $IP_ADDRESS/24 dev $VETH
ip netns exec $NAMESPACE ip link set $VETH up
ip netns exec $NAMESPACE ip link set lo up
ip netns exec $NAMESPACE ip route add default via $PEER_IP
sysctl -w net.ipv4.ip_forward=1
iptables -t nat -A POSTROUTING -s $IP_ADDRESS -o $HOST_IF -j MASQUERADE
iptables -A FORWARD -i $HOST_IF -o $PEER -j ACCEPT
iptables -A FORWARD -o $HOST_IF -i $PEER -j ACCEPT

echo "--- Testing network connectivity ---"

# Configure DNS inside the namespace
ip netns exec $NAMESPACE bash -c 'echo "nameserver 8.8.8.8" > /etc/resolv.conf'

# Run the test command
ip netns exec $NAMESPACE curl -s https://example.com | grep "Example Domain"

echo "--- Tearing down network ---"

# Teardown commands
iptables -D FORWARD -o $HOST_IF -i $PEER -j ACCEPT
iptables -D FORWARD -i $HOST_IF -o $PEER -j ACCEPT
iptables -t nat -D POSTROUTING -s $IP_ADDRESS -o $HOST_IF -j MASQUERADE
ip netns del $NAMESPACE
ip link del $PEER

echo "--- Network verification complete ---"
