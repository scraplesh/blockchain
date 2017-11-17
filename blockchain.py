from gevent import monkey; monkey.patch_all()  # noqa

import collections
import hashlib
import itertools
import json
import time

import bottle
import ecdsa

EMIT_PORTION = 50
CHECK_TRANSACTIONS_DELAY = 3

Wallet = collections.namedtuple('Wallet', ['password_hash', 'private_key'])
TransactionInput = collections.namedtuple('TransactionInput', ['transaction_hash', 'amount'])
TransactionOutput = collections.namedtuple('TransactionOutput', ['wallet_address', 'amount'])
TransactionTransfer = collections.namedtuple('TransactionTransfer', ['inputs', 'output'])
Transaction = collections.namedtuple('Transaction', ['hash', 'transfer'])
Block = collections.namedtuple('Block', ['previous_hash', 'block_hash', 'transactions'])
AvailableAmount = collections.namedtuple('AvailableAmount', ['transaction_hash', 'amount'])

blockchain = []
unconfirmed_transactions = []
wallet = None
is_mining = False


@bottle.post('/create-wallet')
def create_wallet():
    global wallet
    if wallet is not None:
        bottle.abort(400, 'Wallet is already created')

    password = (bottle.request.json or {}).get('password')
    if password is None:
        bottle.abort(400, 'Invalid password')

    password_hash = hashlib.sha1(password.encode()).hexdigest()
    private_key = ecdsa.SigningKey.generate()
    wallet = Wallet(password_hash, private_key)

    return 'Wallet created'


@bottle.post('/create-genesis-block')
def create_genesis_block():
    if blockchain:
        bottle.abort(400, 'Genesis block is already created')

    if wallet is None:
        bottle.abort(400, 'Wallet not found')

    password = (bottle.request.json or {}).get('password')
    if not is_password_valid(wallet, password):
        bottle.abort(400, 'Invalid password')

    receiver_address = get_wallet_address(wallet.private_key)
    output = TransactionOutput(receiver_address, EMIT_PORTION)

    transfer = TransactionTransfer(None, output)
    transaction_hash = get_transaction_hash(transfer)
    transaction = Transaction(transaction_hash, transfer)

    genesis_block = create_block(None, [transaction])
    blockchain.append(genesis_block)

    return 'Genesis block created'


@bottle.post('/create-transaction')
def create_transaction():
    if wallet is None:
        bottle.abort(400, 'Wallet not found')

    password = (bottle.request.json or {}).get('password')
    if not is_password_valid(wallet, password):
        bottle.abort(400, 'Invalid password')

    receiver_address = (bottle.request.json or {}).get('receiver_address')
    if receiver_address is None:
        bottle.abort(400, 'Missing receiver address')

    amount = (bottle.request.json or {}).get('amount')
    if amount is None:
        bottle.abort(400, 'Missing amount')

    current_blockchain = blockchain.copy()
    wallet_address = get_wallet_address(wallet.private_key)
    wallet_balance = get_wallet_balance(current_blockchain, wallet_address)
    if amount > wallet_balance:
        bottle.abort(400, 'Not enough tokens')

    output = TransactionOutput(receiver_address, amount)

    incoming_transactions = (
        transaction
        for block in current_blockchain
        for transaction in block.transactions
        if transaction.transfer.output.wallet_address == wallet_address
    )
    transaction_spends = {
        transaction_input.transaction_hash: sum(
            transaction_input.amount for transaction_input in transaction_inputs
        )
        for transaction_input, transaction_inputs in itertools.groupby(
            sorted(
                (
                    transaction_input
                    for block in current_blockchain
                    for transaction in block.transactions
                    for transaction_input in transaction.transfer.inputs or []
                    for block1 in current_blockchain
                    for transaction1 in block1.transactions
                    if transaction1.hash == transaction_input.transaction_hash and
                    transaction1.transfer.output.wallet_address == wallet_address
                ),
                key=lambda t: t.transaction_hash
            ),
            key=lambda t: t.transaction_hash
        )
    }
    available_amounts = sorted(
        (
            AvailableAmount(
                transaction.hash,
                transaction.transfer.output.amount - transaction_spends.get(transaction.hash, 0)
            )
            for transaction in incoming_transactions
            if transaction.transfer.output.amount - transaction_spends.get(transaction.hash, 0) > 0
        ),
        key=lambda available_amount: available_amount.amount
    )

    inputs = []
    checking_amount = amount
    for available_amount in available_amounts:
        if available_amount.amount >= checking_amount:
            inputs.append(TransactionInput(available_amount.transaction_hash, checking_amount))
            break

        inputs.append(
            TransactionInput(
                available_amount.transaction_hash,
                checking_amount - available_amount.amount
            )
        )
        checking_amount -= available_amount.amount

    transfer = TransactionTransfer(inputs, output)
    transaction_hash = get_transaction_hash(transfer)
    transaction = Transaction(transaction_hash, transfer)

    unconfirmed_transactions.append(transaction)


@bottle.post('/mine')
def mine():
    if not blockchain:
        bottle.abort(400, 'Cannot mine on empty blockchain')

    global is_mining
    is_mining = True
    while is_mining:
        if not unconfirmed_transactions:
            yield 'No transactions to mine. Waiting...\n'
            time.sleep(CHECK_TRANSACTIONS_DELAY)
            continue

        yield 'New transactions found. Mining...\n'

        transactions = unconfirmed_transactions.copy()
        unconfirmed_transactions.clear()

        previous_block = blockchain[-1]
        new_block = create_block(previous_block.block_hash, transactions)

        blockchain.append(new_block)

    yield 'Mining stopped'


@bottle.post('/stop-mining')
def stop_mining():
    global is_mining
    is_mining = False


def create_block(previous_block_hash, transactions):
    block_hash = hashlib.sha1(json.dumps(transactions).encode()).hexdigest()
    return Block(previous_block_hash, block_hash, transactions)


def get_wallet_address(private_key):
    return private_key.get_verifying_key().to_string().hex()


def get_wallet_balance(blockchain, wallet_address):
    income = sum(
        transaction.transfer.output.amount
        for block in blockchain
        for transaction in block.transactions
        if transaction.transfer.output.wallet_address == wallet_address
    )
    waste = sum(
        transaction_input.amount
        for block in blockchain
        for transaction in block.transactions
        for transaction_input in transaction.transfer.inputs or []
        for block1 in blockchain
        for transaction1 in block1.transactions
        if transaction1.hash == transaction_input.transaction_hash and
        transaction1.transfer.output.wallet_address == wallet_address
    )

    return income - waste


def get_transaction_hash(transfer):
    return hashlib.sha1(json.dumps(transfer).encode()).hexdigest()


def is_password_valid(wallet, password):
    return (
        password is not None and
        hashlib.sha1(password.encode()).hexdigest() == wallet.password_hash
    )


bottle.run(host='0.0.0.0', server='gevent')
