import time


class GameState:
    """
    Estado simples da rodada.

    A camera ve a mesma carta em muitos frames. Por isso, as maos atuais sao
    substituidas pela leitura atual da ROI, enquanto seen_cards guarda IDs ja
    vistos sem duplicar continuamente.
    """

    def __init__(self):
        self.seen_cards = []
        self.recent_seen = {}
        self.robot_orders = {}
        self.optimized_chips = {}
        self.reset_round()

    def reset_round(self):
        self.Handsign = 0
        self.Split = 0
        self.player_hands = [[]]
        self.dealer_hand = []
        self.current_bet = 0
        self.original_bet = 0
        self.optimized_chips = {}
        self.robot_orders = {}

    def add_seen_card(self, card, area_name="unknown"):
        card_id = card.get("card_id")
        if card_id is None:
            return

        key = (area_name, card_id)
        now = time.time()

        # Evita adicionar repetidamente a mesma carta vista no mesmo local.
        if key in self.recent_seen and now - self.recent_seen[key] < 2.0:
            return

        self.recent_seen[key] = now

        if not any(seen.get("card_id") == card_id for seen in self.seen_cards):
            self.seen_cards.append(card)

    def update_player_cards(self, cards, hand_index=0):
        while len(self.player_hands) <= hand_index:
            self.player_hands.append([])

        self.player_hands[hand_index] = cards
        for card in cards:
            self.add_seen_card(card, area_name=f"player_{hand_index}")

    def update_dealer_cards(self, cards):
        self.dealer_hand = cards
        for card in cards:
            self.add_seen_card(card, area_name="dealer")

    def start_new_round_if_needed(self):
        """
        Placeholder didatico.

        Em uma versao futura, esta funcao pode detectar fim de rodada por
        bust, blackjack ou estado externo vindo do fluxo do jogo.
        """
        return False
